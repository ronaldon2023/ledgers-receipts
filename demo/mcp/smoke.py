"""Check that both MCP servers work. Run from the repo root with the venv active.

    python demo/mcp/smoke.py                       start both servers directly (no firewall)
    python demo/mcp/smoke.py --bakery-url U --bakesupply-url U    test them through a firewall

Direct mode uses temporary databases and also pays the bill. URL mode only runs checks that
change nothing, so it is safe against the demo database. Exits 1 if any check fails.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from bakery.seed import seed as seed_bakery
from bakesupply.seed import seed as seed_bakesupply

ROOT = Path(__file__).resolve().parents[2]
failures = 0


def check(ok: bool, label: str) -> None:
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def data(result):
    if result.structuredContent:
        return result.structuredContent
    texts = [c.text for c in result.content if hasattr(c, "text")]
    return json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]


@asynccontextmanager
async def connect(module: str, env: dict, url: str | None):
    if url:
        async with (
            streamablehttp_client(url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env={**get_default_environment(), **env},
        cwd=ROOT,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session, tool: str, **args):
    return data(await session.call_tool(tool, args))


async def bakery(url: str | None, db: str) -> None:
    async with connect("bakery.server", {"BAKERY_DB": db}, url) as s:
        names = {t.name for t in (await s.list_tools()).tools}
        check({"list_bills", "pay_bill"} <= names, "bakery: tools are listed")
        bills = await call(s, "list_bills")
        check("BILL-07" in json.dumps(bills), "bakery: BILL-07 is an open bill")
        fraud = await call(
            s, "pay_bill", bill_id="BILL-07", amount_cents=80000, to_account="9876543210"
        )
        check(fraud.get("ok") is False, "bakery: payment to the account ending 3210 is blocked")
        if url:
            return
        paid = await call(
            s, "pay_bill", bill_id="BILL-07", amount_cents=80000, to_account="000123454471"
        )
        check(paid.get("ok") is True, "bakery: payment to the account on file goes through")
        again = await call(
            s, "pay_bill", bill_id="BILL-07", amount_cents=80000, to_account="000123454471"
        )
        check(again.get("ok") is False, "bakery: paying the same bill twice is blocked")


async def bakesupply(url: str | None, db: str) -> None:
    async with connect("bakesupply.server", {"BAKESUPPLY_DB": db}, url) as s:
        names = {t.name for t in (await s.list_tools()).tools}
        check(
            {"place_order", "get_price", "list_products"} <= names, "bakesupply: tools are listed"
        )
        quote = await call(s, "get_price", sku="FLR-AP-50", quantity=12)
        check(quote.get("total_cents") == 60000, "bakesupply: 12 bags of flour quote $600.00")
        if url:
            return
        order = await call(s, "place_order", sku="FLR-AP-50", quantity=2)
        check(
            order.get("ok") is True and order.get("total_cents") == 10000,
            "bakesupply: an order is accepted",
        )
        bad = await call(s, "place_order", sku="FLR-AP-50", quantity=0)
        check(bad.get("ok") is False, "bakesupply: a bad quantity is refused")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bakery-url")
    parser.add_argument("--bakesupply-url")
    opts = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        bakery_db, supply_db = str(Path(tmp) / "bakery.db"), str(Path(tmp) / "bakesupply.db")
        seed_bakery(bakery_db)
        seed_bakesupply(Path(supply_db))
        print("through the firewall" if opts.bakery_url else "direct, no firewall")
        await bakery(opts.bakery_url, bakery_db)
        await bakesupply(opts.bakesupply_url, supply_db)
    print("ALL PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
