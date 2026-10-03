"""Small, curated development catalogue; no learner activity or solutions."""

from dataclasses import dataclass


DEMO_SOURCE = "dev-demo-v1"


@dataclass(frozen=True)
class DemoCase:
    input: str
    expected_output: str
    is_sample: bool


@dataclass(frozen=True)
class DemoProblem:
    title: str
    skill: str
    difficulty: str
    description: str
    constraints: str
    input_format: str
    output_format: str
    expected_complexity: str
    cases: tuple[DemoCase, ...]


DEMO_SKILLS = {
    "Arrays": "Traverse and aggregate arrays; build and reason about prefix sums.",
    "Hashing": "Use hash-based membership and frequency information in sequence problems.",
}

DEMO_PROBLEMS = (
    DemoProblem(
        title="Sum an Array", skill="Arrays", difficulty="Easy",
        description="Given an array of integers, print the sum of its elements.",
        constraints="1 <= n <= 100000; -1000000000 <= each value <= 1000000000.",
        input_format="The first line contains n. The second line contains n space-separated integers.",
        output_format="Print one integer: the sum.", expected_complexity="O(n) time, O(1) extra space",
        cases=(DemoCase("3\n1 2 3\n", "6\n", True),
               DemoCase("4\n-3 0 8 -2\n", "3\n", True),
               DemoCase("1\n-7\n", "-7\n", False),
               DemoCase("3\n1000000000 1000000000 1000000000\n", "3000000000\n", False)),
    ),
    DemoProblem(
        title="Maximum Array Element", skill="Arrays", difficulty="Easy",
        description="Given a nonempty array of integers, print its largest element.",
        constraints="1 <= n <= 100000; -1000000000 <= each value <= 1000000000.",
        input_format="The first line contains n. The second line contains n space-separated integers.",
        output_format="Print one integer: the maximum element.",
        expected_complexity="O(n) time, O(1) extra space",
        cases=(DemoCase("5\n3 -4 7 0 2\n", "7\n", True),
               DemoCase("3\n-8 -2 -5\n", "-2\n", True),
               DemoCase("1\n-1000000000\n", "-1000000000\n", False),
               DemoCase("4\n9 9 9 9\n", "9\n", False)),
    ),
    DemoProblem(
        title="Range Sum Queries", skill="Arrays", difficulty="Medium",
        description="Answer q sum queries on an immutable array. Each query asks for the sum "
                    "from position l through r, inclusive, using one-based positions.",
        constraints="1 <= n, q <= 100000; 1 <= l <= r <= n; values are between -1000000000 and 1000000000.",
        input_format="First line: n q. Second line: n integers. Each of the next q lines contains l r.",
        output_format="Print each query's sum on a separate line.",
        expected_complexity="O(n + q) time, O(n) extra space",
        cases=(DemoCase("5 3\n1 2 3 4 5\n1 3\n2 5\n3 3\n", "6\n14\n3\n", True),
               DemoCase("3 2\n-2 5 -1\n1 3\n2 2\n", "2\n5\n", True),
               DemoCase("1 2\n-7\n1 1\n1 1\n", "-7\n-7\n", False),
               DemoCase("4 3\n0 0 0 0\n1 4\n1 1\n2 3\n", "0\n0\n0\n", False)),
    ),
    DemoProblem(
        title="Count Subarray Sums in a Range", skill="Arrays", difficulty="Hard",
        description="Count nonempty contiguous subarrays whose sum lies between lower and upper, "
                    "inclusive. Print the count; do not enumerate the subarrays.",
        constraints="1 <= n <= 100000; -1000000000 <= values, lower, upper <= 1000000000; lower <= upper.",
        input_format="First line: n lower upper. Second line: n space-separated integers.",
        output_format="Print one integer: the number of qualifying subarrays.",
        expected_complexity="O(n log n) time, O(n) extra space",
        cases=(DemoCase("3 -2 2\n-2 5 -1\n", "3\n", True),
               DemoCase("3 1 3\n1 1 1\n", "6\n", True),
               DemoCase("4 0 0\n0 0 0 0\n", "10\n", False),
               DemoCase("3 -3 -1\n-1 -1 -1\n", "6\n", False)),
    ),
    DemoProblem(
        title="First Duplicate Value", skill="Hashing", difficulty="Easy",
        description="Scan the array from left to right. Print the value whose occurrence is the "
                    "first to repeat an earlier value. Print -1 if no value repeats.",
        constraints="1 <= n <= 100000; 0 <= each value <= 1000000000.",
        input_format="The first line contains n. The second line contains n space-separated integers.",
        output_format="Print the first repeated value, or -1.",
        expected_complexity="O(n) expected time, O(n) extra space",
        cases=(DemoCase("6\n2 1 3 2 1 4\n", "2\n", True),
               DemoCase("3\n1 2 3\n", "-1\n", True),
               DemoCase("1\n0\n", "-1\n", False),
               DemoCase("4\n0 0 1 1\n", "0\n", False)),
    ),
    DemoProblem(
        title="Longest Distinct Substring", skill="Hashing", difficulty="Medium",
        description="Given a string, print the length of its longest contiguous substring "
                    "containing no repeated character. An empty string has answer 0.",
        constraints="0 <= string length <= 100000; characters are lowercase English letters.",
        input_format="One line containing the string (the line may be empty).",
        output_format="Print one integer: the maximum length.",
        expected_complexity="O(n) expected time, O(26) extra space",
        cases=(DemoCase("abcabcbb\n", "3\n", True),
               DemoCase("pwwkew\n", "3\n", True),
               DemoCase("\n", "0\n", False),
               DemoCase("abba\n", "2\n", False),
               DemoCase("bbbbb\n", "1\n", False)),
    ),
)
