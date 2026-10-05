"""Bounded offline-first tutor experiments, comparison and explicit human review."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.benchmark import ExecutionPolicy, HumanReviewCreate, PricingSnapshot
from app.services.benchmark_suite import load_suite
from app.services.evaluation_provider_factory import build_provider, parse_candidate
from app.services.evaluation_report import compare_group, export_group
from app.services.evaluation_runner import invoke_case
from app.services import evaluation_store


DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "benchmarks" / "tutor" / "v1" / "suite.json"


def create_evaluation_session_factory() -> sessionmaker[Session]:
    """Resolve database-only configuration; never initialize application providers."""

    class DatabaseConfiguration(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")
        database_url: str = Field(repr=False, validation_alias="DATABASE_URL")
        app_env: str = Field(default="development", validation_alias="APP_ENV")

    settings = DatabaseConfiguration()
    from scripts.provision_demo import validate_local_demo_database

    validate_local_demo_database(settings.app_env, settings.database_url)
    return sessionmaker(bind=create_engine(settings.database_url, pool_pre_ping=True))


def _read_json(path: Path, maximum_bytes: int = 128_000):
    if path.stat().st_size > maximum_bytes:
        raise ValueError("Input file exceeds the evaluation import bound")
    return json.loads(path.read_text(encoding="utf-8"))


def _git_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True,
                                        stderr=subprocess.DEVNULL).strip()
        return f"dirty-{revision}" if dirty else revision
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _emit(value, output: Path | None = None) -> None:
    serialized = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    if output is not None:
        # Avoid overwriting a review/export accidentally.
        with output.open("x", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
        print("Evaluation export written to the explicitly selected file.")
    else:
        print(serialized)


def _warn_live_cost(maximum_invocations: int) -> None:
    print(f"LIVE experiment: up to {maximum_invocations} external invocations. "
          "Charges may apply; total cost is unknown without complete reported tokens and compatible pricing. "
          "Explicit cost acknowledgment does not select a production model.", file=sys.stderr)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run synthetic candidates by default; live requires all explicit gates")
    run.add_argument("--suite", type=Path)
    run.add_argument("--suite-version")
    run.add_argument("--candidate", action="append")
    run.add_argument("--case")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--live", action="store_true")
    run.add_argument("--max-calls", type=int)
    run.add_argument("--timeout-seconds", type=float)
    run.add_argument("--max-retries", type=int, default=0)
    run.add_argument("--max-input-chars", type=int, default=30000)
    run.add_argument("--max-output-tokens", type=int, default=2048)
    run.add_argument("--temperature", type=float, default=0)
    run.add_argument("--acknowledge-live-cost", action="store_true")
    run.add_argument("--group-id", type=UUID)
    run.add_argument("--resume-run", type=UUID)
    run.add_argument("--pricing", type=Path, help="Explicit JSON list of versioned provider/model prices; never fetched")
    for name in ("compare", "export"):
        command = commands.add_parser(name)
        command.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
        command.add_argument("--group-id", type=UUID, required=True)
        command.add_argument("--output", type=Path)
    review = commands.add_parser("review", help="Append a bounded human review JSON record")
    review.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    review.add_argument("--input", type=Path, required=True)
    return result


async def _run(arguments) -> int:
    loaded = load_suite(arguments.suite or DEFAULT_SUITE)
    if arguments.suite_version is not None and arguments.suite_version != loaded.suite.version:
        raise ValueError("Explicit suite version does not match its definition")
    candidates = [parse_candidate(spec) for spec in (arguments.candidate or ["synthetic-good", "synthetic-bad"])]
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise ValueError("Candidate identities must be unique")
    cases = list(loaded.suite.cases)
    if arguments.case:
        if arguments.case not in loaded.case_by_id:
            raise ValueError("Unknown benchmark case identity")
        cases = [loaded.case_by_id[arguments.case]]
    policy = ExecutionPolicy(timeout_seconds=30 if arguments.timeout_seconds is None else arguments.timeout_seconds,
                             max_retries=arguments.max_retries, max_input_chars=arguments.max_input_chars,
                             max_output_tokens=arguments.max_output_tokens, temperature=arguments.temperature)
    worst_case_calls = len(cases) * len(candidates) * (1 + policy.max_retries)
    revision = _git_revision()
    external = any(not candidate.synthetic for candidate in candidates)
    if arguments.live:
        if (not external or any(candidate.synthetic for candidate in candidates)
                or not arguments.candidate or not arguments.suite or not arguments.suite_version
                or arguments.timeout_seconds is None or not arguments.acknowledge_live_cost
                or arguments.max_calls is None or not 1 <= arguments.max_calls <= 1000
                or worst_case_calls > arguments.max_calls):
            raise ValueError("Live execution requires explicit real candidates, suite/version, timeout, sufficient bounded calls and cost acknowledgment")
        if revision.startswith("dirty-") or revision == "unknown":
            raise ValueError("Live experiments require an identifiable clean Git checkpoint")
        if not (policy.timeout_seconds <= 120 and 1000 <= policy.max_input_chars <= 60000
                and 128 <= policy.max_output_tokens <= 4096):
            raise ValueError("Live controls exceed the registered adapter bounds")
    elif external:
        raise ValueError("External candidates require explicit live opt-in; offline mode never constructs them")
    elif arguments.max_calls is not None and (arguments.max_calls < worst_case_calls or arguments.max_calls > 1000):
        raise ValueError("Maximum calls does not cover the selected bounded experiment")
    if arguments.resume_run and len(candidates) != 1:
        raise ValueError("Resume selects exactly one candidate")
    prices = []
    if arguments.pricing:
        values = _read_json(arguments.pricing)
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("Pricing input must be a bounded list")
        prices = [PricingSnapshot.model_validate(value) for value in values]
        identities = [(price.provider, price.model_id, price.synthetic) for price in prices]
        if len(set(identities)) != len(identities):
            raise ValueError("Pricing snapshots must identify unique candidates")
    plan = {"mode": "LIVE" if arguments.live else "SYNTHETIC_OR_DRY_RUN",
            "suite_id": loaded.suite.suite_id, "suite_version": loaded.suite.version,
            "suite_digest": loaded.digest, "selected_cases": [case.case_id for case in cases],
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            "policy": policy.model_dump(mode="json"), "maximum_invocations": worst_case_calls,
            "code_revision": revision,
            "cost_warning": "Cost is unavailable without compatible reported tokens and explicit pricing. No model is selected."}
    if arguments.dry_run:
        _emit(plan)
        return 0
    if arguments.live:
        _warn_live_cost(worst_case_calls)
    factory = create_evaluation_session_factory()
    group_id = arguments.group_id or uuid4()
    if arguments.resume_run:
        with factory() as db:
            previous = evaluation_store.get_run(db, arguments.resume_run)
            if arguments.group_id is not None and arguments.group_id != previous.group_id:
                raise ValueError("Resume group differs from the recorded plan")
            group_id = previous.group_id
    for candidate in candidates:
        matching = [price for price in prices if (price.provider, price.model_id, price.synthetic)
                    == (candidate.provider, candidate.model_id, candidate.synthetic)]
        with factory() as db:
            run = evaluation_store.start_run(db, candidate=candidate, loaded_suite=loaded, policy=policy,
                                             selected_cases=cases, group_id=group_id,
                                             pricing=matching[0] if matching else None, code_revision=revision,
                                             run_id=arguments.resume_run)
            run_id = run.id
            existing = {result.case_id for result in evaluation_store.results_for_run(db, run_id)}
        for case in cases:
            if case.case_id in existing:
                continue
            provider = build_provider(candidate, case, policy, live_authorized=arguments.live)
            observation = await invoke_case(provider, case, candidate, policy)
            with factory() as db:
                evaluation_store.record_result(db, run_id, case, observation)
        with factory() as db:
            evaluation_store.finish_run(db, run_id)
    with factory() as db:
        _emit(compare_group(db, group_id, loaded))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "run":
            return asyncio.run(_run(arguments))
        loaded = load_suite(arguments.suite)
        payload = HumanReviewCreate.model_validate(_read_json(arguments.input)) if arguments.command == "review" else None
        factory = create_evaluation_session_factory()
        with factory() as db:
            if arguments.command == "review":
                review = evaluation_store.record_review(db, payload, loaded)
                _emit({"review_id": review.id, "result_id": review.result_id, "source": "HUMAN"})
            elif arguments.command == "compare":
                _emit(compare_group(db, arguments.group_id, loaded), arguments.output)
            else:
                _emit(export_group(db, arguments.group_id, loaded), arguments.output)
        return 0
    except (ValidationError, ValueError, OSError, SQLAlchemyError):
        # User input and DB/SDK diagnostics can include credentials; never print them.
        print("Evaluation operation refused or failed safely. Check definitions, explicit flags and local database migration state; no private diagnostics are displayed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
