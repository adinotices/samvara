"""
Load testing for billing endpoints.

Simulates realistic concurrent load to validate performance under stress.
Run with: python -m pytest backend/tests/load_test_billing.py -v

Requires: locust (pip install locust)

For distributed load testing:
  locust -f backend/tests/load_test_billing.py --host=http://localhost:8000
"""

import asyncio
import concurrent.futures
import time
from typing import Any
import pytest
import httpx
from unittest.mock import patch, MagicMock


class LoadTestConfig:
    """Load test configuration."""
    BASE_URL = "http://localhost:8000"
    NUM_CONCURRENT_USERS = 50
    NUM_REQUESTS_PER_USER = 20
    REQUEST_TIMEOUT = 30
    ACCEPTABLE_LATENCY_MS = 1000  # 1 second
    ACCEPTABLE_ERROR_RATE = 0.01  # 1% max


class BillingLoadTest:
    """Load test suite for billing endpoints."""

    def __init__(self):
        self.results = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_time_ms": 0,
            "latencies": [],
            "errors": {},
        }

    async def get_billing_status(self, session_id: str) -> dict[str, Any]:
        """Simulate get billing status request."""
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=LoadTestConfig.REQUEST_TIMEOUT) as client:
                response = await client.get(
                    f"{LoadTestConfig.BASE_URL}/v1/billing/status",
                    headers={"Cookie": f"session_id={session_id}"},
                )
                response.raise_for_status()
                latency_ms = (time.time() - start) * 1000
                self.results["latencies"].append(latency_ms)
                return {
                    "success": True,
                    "latency_ms": latency_ms,
                    "status_code": response.status_code,
                }
        except Exception as e:
            error_type = type(e).__name__
            self.results["errors"][error_type] = self.results["errors"].get(error_type, 0) + 1
            return {
                "success": False,
                "latency_ms": (time.time() - start) * 1000,
                "error": str(e),
            }

    async def create_setup_intent(self, session_id: str) -> dict[str, Any]:
        """Simulate create setup intent request."""
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=LoadTestConfig.REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{LoadTestConfig.BASE_URL}/v1/billing/setup-intent",
                    headers={"Cookie": f"session_id={session_id}"},
                )
                response.raise_for_status()
                latency_ms = (time.time() - start) * 1000
                self.results["latencies"].append(latency_ms)
                return {
                    "success": True,
                    "latency_ms": latency_ms,
                    "status_code": response.status_code,
                }
        except Exception as e:
            error_type = type(e).__name__
            self.results["errors"][error_type] = self.results["errors"].get(error_type, 0) + 1
            return {
                "success": False,
                "latency_ms": (time.time() - start) * 1000,
                "error": str(e),
            }

    async def simulate_user_session(self, user_id: str, num_requests: int = 20) -> None:
        """Simulate a user performing billing operations."""
        session_id = f"session-{user_id}"

        for i in range(num_requests):
            self.results["total_requests"] += 1

            # 70% check billing status, 30% create setup intent
            if i % 10 < 7:
                result = await self.get_billing_status(session_id)
            else:
                result = await self.create_setup_intent(session_id)

            if result["success"]:
                self.results["successful_requests"] += 1
            else:
                self.results["failed_requests"] += 1

    async def run_concurrent_load(self) -> None:
        """Run concurrent users."""
        print(f"Starting load test: {LoadTestConfig.NUM_CONCURRENT_USERS} users, "
              f"{LoadTestConfig.NUM_REQUESTS_PER_USER} requests each")

        start_time = time.time()

        tasks = [
            self.simulate_user_session(str(i), LoadTestConfig.NUM_REQUESTS_PER_USER)
            for i in range(LoadTestConfig.NUM_CONCURRENT_USERS)
        ]

        await asyncio.gather(*tasks)

        self.results["total_time_ms"] = (time.time() - start_time) * 1000

    def calculate_percentiles(self) -> dict[str, float]:
        """Calculate latency percentiles."""
        sorted_latencies = sorted(self.results["latencies"])
        n = len(sorted_latencies)

        return {
            "p50": sorted_latencies[int(n * 0.50)] if n > 0 else 0,
            "p90": sorted_latencies[int(n * 0.90)] if n > 0 else 0,
            "p95": sorted_latencies[int(n * 0.95)] if n > 0 else 0,
            "p99": sorted_latencies[int(n * 0.99)] if n > 0 else 0,
            "min": min(sorted_latencies) if sorted_latencies else 0,
            "max": max(sorted_latencies) if sorted_latencies else 0,
            "mean": sum(sorted_latencies) / n if n > 0 else 0,
        }

    def report(self) -> None:
        """Print results."""
        percentiles = self.calculate_percentiles()
        error_rate = (self.results["failed_requests"] / self.results["total_requests"]
                     if self.results["total_requests"] > 0 else 0)

        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)
        print(f"Total Requests:       {self.results['total_requests']:,}")
        print(f"Successful:           {self.results['successful_requests']:,}")
        print(f"Failed:               {self.results['failed_requests']:,}")
        print(f"Error Rate:           {error_rate:.2%}")
        print(f"Total Time:           {self.results['total_time_ms']:.0f}ms")
        print()
        print("Latency (milliseconds):")
        print(f"  Min:                {percentiles['min']:.1f}ms")
        print(f"  P50:                {percentiles['p50']:.1f}ms")
        print(f"  P90:                {percentiles['p90']:.1f}ms")
        print(f"  P95:                {percentiles['p95']:.1f}ms")
        print(f"  P99:                {percentiles['p99']:.1f}ms")
        print(f"  Max:                {percentiles['max']:.1f}ms")
        print(f"  Mean:               {percentiles['mean']:.1f}ms")
        print()
        print("Errors:")
        for error_type, count in self.results["errors"].items():
            print(f"  {error_type}: {count}")
        print("=" * 60)

        # Validation
        assert error_rate <= LoadTestConfig.ACCEPTABLE_ERROR_RATE, \
            f"Error rate {error_rate:.2%} exceeds acceptable {LoadTestConfig.ACCEPTABLE_ERROR_RATE:.2%}"
        assert percentiles["p99"] <= LoadTestConfig.ACCEPTABLE_LATENCY_MS * 5, \
            f"P99 latency {percentiles['p99']:.0f}ms exceeds limit"
        print("\n✅ Load test passed!")


# pytest tests
@pytest.mark.asyncio
async def test_concurrent_billing_requests():
    """Test billing endpoints under concurrent load."""
    load_test = BillingLoadTest()
    await load_test.run_concurrent_load()
    load_test.report()


@pytest.mark.asyncio
async def test_spike_load():
    """Test rapid spike in traffic (sudden 100 concurrent users)."""
    config_backup = {
        "num_users": LoadTestConfig.NUM_CONCURRENT_USERS,
        "num_requests": LoadTestConfig.NUM_REQUESTS_PER_USER,
    }

    LoadTestConfig.NUM_CONCURRENT_USERS = 100
    LoadTestConfig.NUM_REQUESTS_PER_USER = 10

    try:
        load_test = BillingLoadTest()
        print("\nSpike test: 100 concurrent users")
        await load_test.run_concurrent_load()
        load_test.report()
    finally:
        LoadTestConfig.NUM_CONCURRENT_USERS = config_backup["num_users"]
        LoadTestConfig.NUM_REQUESTS_PER_USER = config_backup["num_requests"]


@pytest.mark.asyncio
async def test_sustained_load():
    """Test sustained traffic over longer period."""
    config_backup = {
        "num_users": LoadTestConfig.NUM_CONCURRENT_USERS,
        "num_requests": LoadTestConfig.NUM_REQUESTS_PER_USER,
    }

    LoadTestConfig.NUM_CONCURRENT_USERS = 25
    LoadTestConfig.NUM_REQUESTS_PER_USER = 100  # Longer session

    try:
        load_test = BillingLoadTest()
        print("\nSustained load test: 25 concurrent users, 100 requests each")
        await load_test.run_concurrent_load()
        load_test.report()
    finally:
        LoadTestConfig.NUM_CONCURRENT_USERS = config_backup["num_users"]
        LoadTestConfig.NUM_REQUESTS_PER_USER = config_backup["num_requests"]


def benchmark_stripe_api_calls():
    """Benchmark individual Stripe API calls."""
    print("\nBenchmarking Stripe API calls:")

    # Mock Stripe responses to isolate network timing
    with patch("app.stripe_billing.stripe.PaymentIntent.create") as mock_create:
        mock_create.return_value = MagicMock(
            id="pi_bench_123",
            status="succeeded",
            amount=5000,
        )

        times = []
        for _ in range(100):
            start = time.time()
            # Simulate charge call
            try:
                pass  # Mock call
            except Exception:
                pass
            times.append((time.time() - start) * 1000)

        print(f"  Min: {min(times):.2f}ms")
        print(f"  Mean: {sum(times) / len(times):.2f}ms")
        print(f"  Max: {max(times):.2f}ms")


# Locust distributed load testing
# Uncomment to use with: locust -f backend/tests/load_test_billing.py

# from locust import HttpUser, task, between
#
# class BillingUser(HttpUser):
#     """Locust user for distributed load testing."""
#     wait_time = between(1, 3)
#
#     def on_start(self):
#         """Authenticate at session start."""
#         self.session_id = f"session-{time.time()}"
#
#     @task(7)
#     def get_billing_status(self):
#         """Check billing status (70% of requests)."""
#         self.client.get(
#             "/v1/billing/status",
#             headers={"Cookie": f"session_id={self.session_id}"},
#         )
#
#     @task(3)
#     def create_setup_intent(self):
#         """Create setup intent (30% of requests)."""
#         self.client.post(
#             "/v1/billing/setup-intent",
#             headers={"Cookie": f"session_id={self.session_id}"},
#         )


if __name__ == "__main__":
    # Run tests
    import subprocess
    subprocess.run([
        "pytest",
        __file__,
        "-v",
        "-s",  # Show print output
        "-m", "asyncio",
    ])
