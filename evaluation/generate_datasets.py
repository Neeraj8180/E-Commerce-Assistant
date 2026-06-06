"""Expand evaluation datasets to ~100 cases per agent scope.

Cycles seed-order scenarios with paraphrased user queries so recruiters and
the eval harness see broad coverage without hand-writing hundreds of lines.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation" / "dataset"
TARGET = 100

USERS = ["alice@example.com", "bob@example.com", "carol@example.com"]

RETURN_SCENARIOS = [
    {
        "order_id": "ORD-1001",
        "reason": "didn't fit",
        "item_skus": None,
        "outcome": "approved_auto",
        "tools": ["get_order", "search_policies", "shopify_create_return", "stripe_process_refund"],
        "templates": [
            "I want to return order {oid}, {reason}.",
            "Please refund my order {oid} — {reason}.",
            "Can I send back {oid}? {reason}.",
            "I'd like a refund for {oid}, {reason}.",
            "Return request for {oid}: {reason}.",
        ],
    },
    {
        "order_id": "ORD-1002",
        "reason": "changed mind",
        "item_skus": ["HEADPHONES-X1"],
        "outcome": "approved_manager_review",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "Please refund order {oid}, {reason}.",
            "I need to return the headphones from {oid}, {reason}.",
            "Refund {oid} — {reason}.",
            "Send back order {oid}, {reason}.",
            "Return {oid} please, {reason}.",
        ],
    },
    {
        "order_id": "ORD-1003",
        "reason": "too old",
        "item_skus": None,
        "outcome": "rejected_window",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "I'd like a refund for {oid}, {reason}.",
            "Refund for {oid} — it's been a while.",
            "Can I still return {oid}? {reason}.",
            "Return {oid} please.",
            "I want my money back for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1004",
        "reason": "don't want it",
        "item_skus": None,
        "outcome": "rejected_status",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "Can I return order {oid}?",
            "Refund {oid} — {reason}.",
            "I want to send back {oid}.",
            "Return {oid}, {reason}.",
            "Please process a return for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1005",
        "reason": "changed mind",
        "item_skus": None,
        "outcome": "rejected_status",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "Send back order {oid}.",
            "Return {oid}, {reason}.",
            "I'd like to refund {oid}.",
            "Can I return {oid}? {reason}.",
            "Refund request for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1006",
        "reason": "defective",
        "item_skus": None,
        "outcome": "approved_manager_review",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "I want to return my tablet, order {oid}.",
            "Return {oid} — the tablet is broken.",
            "Refund {oid}, item is defective.",
            "Please return order {oid}, {reason}.",
            "I'd like a refund for {oid}, {reason}.",
        ],
    },
    {
        "order_id": "ORD-1008",
        "reason": "changed mind",
        "item_skus": None,
        "outcome": "rejected_status",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "return order {oid}",
            "Refund {oid} please.",
            "I want to send back {oid}.",
            "Return {oid}, {reason}.",
            "Can you refund {oid}?",
        ],
    },
    {
        "order_id": "ORD-1009",
        "reason": "size issue",
        "item_skus": None,
        "outcome": "approved_auto",
        "tools": ["get_order", "search_policies", "shopify_create_return", "stripe_process_refund"],
        "templates": [
            "I'd like to send back {oid}, the jeans don't fit.",
            "Return {oid} — {reason}.",
            "Refund order {oid}, {reason}.",
            "Please return {oid}, {reason}.",
            "I want a refund for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1010",
        "reason": "damaged in transit",
        "item_skus": ["BOOK-COOK-01"],
        "outcome": "approved_auto",
        "tools": ["get_order", "search_policies", "shopify_create_return", "stripe_process_refund"],
        "templates": [
            "Return please for order {oid}, it arrived damaged.",
            "Refund the cookbook from {oid}, damaged.",
            "please refund {oid}, it was damaged",
            "Return {oid} — {reason}.",
            "I'd like a refund for {oid}, {reason}.",
        ],
    },
    {
        "order_id": "ORD-9999",
        "reason": "didn't fit",
        "item_skus": None,
        "outcome": "rejected_not_found",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "Refund order {oid} please.",
            "I want to return {oid}.",
            "Return {oid}, {reason}.",
            "Can I get a refund for {oid}?",
            "Please process return for {oid}.",
        ],
    },
    {
        "order_id": None,
        "reason": None,
        "item_skus": None,
        "outcome": "missing_order_id",
        "tools": ["search_policies"],
        "templates": [
            "Hi, I want to return something I ordered.",
            "send back my order",
            "I need a refund please",
            "Can I return my recent purchase?",
            "I'd like to send something back.",
        ],
    },
]

EXCHANGE_SCENARIOS = [
    {
        "order_id": "ORD-1009",
        "original_sku": "JEANS-BLU-32",
        "new_sku": "JEANS-BLU-33",
        "reason": "size issue",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "I want to exchange my jeans for a different size, order {oid}.",
            "Swap jeans in {oid} from 32 to 33.",
            "Exchange {oid}: size issue.",
            "Please exchange jeans on {oid}.",
            "Different size for {oid} please.",
        ],
    },
    {
        "order_id": "ORD-1009",
        "original_sku": "JEANS-BLU-32",
        "new_sku": "JEANS-BLU-34",
        "reason": "size issue",
        "outcome": "exchange_out_of_stock",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "Can I swap the jeans in {oid} for size 34?",
            "Exchange jeans (32) for 34 in {oid}.",
            "Please exchange {oid} jeans to size 34.",
            "Swap size 34 for {oid}.",
            "Exchange {oid} — need size 34.",
        ],
    },
    {
        "order_id": "ORD-1001",
        "original_sku": "TSHIRT-BLU-M",
        "new_sku": "TSHIRT-RED-M",
        "reason": "prefer red",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "I want to swap the t-shirt in {oid} for a different color.",
            "Exchange t-shirt on {oid} for red.",
            "Swap {oid} shirt color please.",
            "Exchange {oid} — prefer red.",
            "Replace t-shirt in {oid}.",
        ],
    },
    {
        "order_id": "ORD-1001",
        "original_sku": "TSHIRT-BLU-M",
        "new_sku": "TSHIRT-BLU-L",
        "reason": "size",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "different size please for my order {oid} t-shirt",
            "Exchange {oid} shirt to size L.",
            "Swap t-shirt size on {oid}.",
            "Need larger size for {oid}.",
            "Exchange {oid} — size up.",
        ],
    },
    {
        "order_id": "ORD-1002",
        "original_sku": "HEADPHONES-X1",
        "new_sku": "HEADPHONES-X1-SLV",
        "reason": "color preference",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "Exchange my headphones ({oid}) for the silver model.",
            "Swap headphones on {oid} to silver.",
            "Exchange {oid} — silver color.",
            "Replace headphones in {oid}.",
            "I'd like silver headphones for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1003",
        "original_sku": "SNEAKER-RED-10",
        "new_sku": "SNEAKER-RED-11",
        "reason": "too small",
        "outcome": "rejected_window",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "I'd like to exchange the sneakers in {oid} for size 11.",
            "Swap sneakers on {oid} to size 11.",
            "Exchange {oid} — too small.",
            "Different sneaker size for {oid}.",
            "Replace sneakers in {oid}.",
        ],
    },
    {
        "order_id": "ORD-1004",
        "original_sku": "JACKET-BLK-L",
        "new_sku": "JACKET-BLK-XL",
        "reason": "too small",
        "outcome": "rejected_status",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "Can I exchange {oid} for a different jacket size?",
            "Swap jacket size on {oid}.",
            "Exchange {oid} jacket to XL.",
            "Replace jacket in {oid}.",
            "Need bigger jacket for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1005",
        "original_sku": "MUG-CER-WHT",
        "new_sku": "MUG-CER-BLK",
        "reason": "color",
        "outcome": "rejected_status",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "I want to exchange the mug from {oid}",
            "Swap mug color on {oid}.",
            "Exchange {oid} mug to black.",
            "Replace mug in {oid}.",
            "Different mug for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1006",
        "original_sku": "TABLET-PRO-10",
        "new_sku": "TABLET-PRO-10-SLV",
        "reason": "color",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "Can I swap the tablet ({oid}) for the silver one?",
            "Exchange tablet on {oid} to silver.",
            "Swap {oid} tablet color.",
            "Replace tablet in {oid}.",
            "Silver tablet exchange for {oid}.",
        ],
    },
    {
        "order_id": "ORD-1010",
        "original_sku": "BOOK-COOK-01",
        "new_sku": "BOOK-COOK-02",
        "reason": "already have vol 1",
        "outcome": "exchange_created",
        "tools": ["get_order", "search_policies", "shopify_create_exchange"],
        "templates": [
            "swap the cookbook in {oid} for volume 2",
            "Exchange cookbook on {oid}.",
            "Replace book in {oid} with vol 2.",
            "Swap {oid} cookbook.",
            "Exchange {oid} — need vol 2.",
        ],
    },
    {
        "order_id": "ORD-9999",
        "original_sku": "X",
        "new_sku": "Y",
        "reason": "swap",
        "outcome": "rejected_not_found",
        "tools": ["get_order", "search_policies"],
        "templates": [
            "exchange {oid} please",
            "Swap items on {oid}.",
            "Exchange order {oid}.",
            "Replace product in {oid}.",
            "I'd like to exchange {oid}.",
        ],
    },
    {
        "order_id": None,
        "original_sku": None,
        "new_sku": None,
        "reason": None,
        "outcome": "missing_exchange_details",
        "tools": ["search_policies"],
        "templates": [
            "I'd like to swap items in my order.",
            "I want to exchange something.",
            "Can I swap my purchase?",
            "Exchange please.",
            "I need a different size.",
        ],
    },
]

WISMO_SCENARIOS = [
    {"order_id": "ORD-1004", "outcome": "in_transit", "tools": ["get_order", "search_policies"],
     "templates": ["Where is my order {oid}?", "tracking for {oid} please", "when will {oid} arrive?",
                   "status of {oid}?", "WISMO {oid}"]},
    {"order_id": "ORD-1001", "outcome": "delivered", "tools": ["get_order", "search_policies"],
     "templates": ["Can you tell me the status of {oid}?", "status of order {oid}", "is {oid} delivered?",
                   "delivery status for {oid}", "has {oid} arrived?"]},
    {"order_id": "ORD-1005", "outcome": "processing", "tools": ["get_order", "search_policies"],
     "templates": ["WISMO {oid}", "where is {oid}?", "status update for {oid}", "is {oid} processing?",
                   "any news on {oid}?"]},
    {"order_id": "ORD-1007", "outcome": "delayed", "tools": ["get_order", "search_policies"],
     "templates": ["Has my order {oid} shipped yet?", "any update on {oid}? it's late",
                   "is {oid} delayed?", "tracking for {oid}", "when is {oid} arriving?"]},
    {"order_id": "ORD-1008", "outcome": "cancelled", "tools": ["get_order", "search_policies"],
     "templates": ["Where is my package, order {oid}?", "status of {oid}", "tracking {oid}",
                   "what happened to {oid}?", "is {oid} still shipping?"]},
    {"order_id": "ORD-1002", "outcome": "delivered", "tools": ["get_order", "search_policies"],
     "templates": ["status of order {oid}", "where is {oid}?", "delivery for {oid}",
                   "has {oid} been delivered?", "update on {oid}"]},
    {"order_id": "ORD-1006", "outcome": "delivered", "tools": ["get_order", "search_policies"],
     "templates": ["my tablet hasn't shown up, {oid}", "where is {oid}?", "status {oid}",
                   "tracking for tablet order {oid}", "delivery status {oid}"]},
    {"order_id": "ORD-1010", "outcome": "delivered", "tools": ["get_order", "search_policies"],
     "templates": ["is my order {oid} delivered?", "status of {oid}", "where is {oid}?",
                   "has {oid} arrived?", "tracking {oid}"]},
    {"order_id": "ORD-1009", "outcome": "delivered", "tools": ["get_order", "search_policies"],
     "templates": ["tracking number for {oid}", "status of {oid}", "where is {oid}?",
                   "delivery update {oid}", "is {oid} delivered?"]},
    {"order_id": "ORD-9999", "outcome": "order_not_found", "tools": ["get_order", "search_policies"],
     "templates": ["is {oid} on its way?", "where is {oid}?", "status of {oid}",
                   "tracking for {oid}", "WISMO {oid}"]},
    {"order_id": None, "outcome": "missing_order_id", "tools": ["search_policies"],
     "templates": ["Where is my order?", "track my package", "when will my order arrive?",
                   "order status please", "WISMO"]},
]


def _expand(prefix: str, scenarios: list[dict], builder) -> list[dict]:
    cases: list[dict] = []
    i = 0
    while len(cases) < TARGET:
        for sc in scenarios:
            if len(cases) >= TARGET:
                break
            tpl = sc["templates"][len(cases) % len(sc["templates"])]
            user = USERS[i % len(USERS)]
            case = builder(prefix, i + 1, sc, tpl, user)
            cases.append(case)
            i += 1
    return cases


def _return_case(prefix: str, n: int, sc: dict, tpl: str, user: str) -> dict:
    oid = sc["order_id"]
    ctx: dict = {}
    if oid:
        ctx["order_id"] = oid
    if sc.get("reason"):
        ctx["reason"] = sc["reason"]
    if sc.get("item_skus"):
        ctx["item_skus"] = sc["item_skus"]
    query = tpl.format(oid=oid or "my order", reason=sc.get("reason") or "")
    return {
        "id": f"{prefix}-{n:03d}",
        "query": query,
        "user_id": user,
        "context": ctx,
        "expected_intent": "return",
        "expected_outcome": sc["outcome"],
        "expected_tools": sc["tools"],
    }


def _exchange_case(prefix: str, n: int, sc: dict, tpl: str, user: str) -> dict:
    oid = sc["order_id"]
    ctx: dict = {}
    if oid:
        ctx["order_id"] = oid
    if sc.get("original_sku"):
        ctx["original_sku"] = sc["original_sku"]
    if sc.get("new_sku"):
        ctx["new_sku"] = sc["new_sku"]
    if sc.get("reason"):
        ctx["reason"] = sc["reason"]
    query = tpl.format(oid=oid or "my order")
    return {
        "id": f"{prefix}-{n:03d}",
        "query": query,
        "user_id": user,
        "context": ctx,
        "expected_intent": "exchange",
        "expected_outcome": sc["outcome"],
        "expected_tools": sc["tools"],
    }


def _wismo_case(prefix: str, n: int, sc: dict, tpl: str, user: str) -> dict:
    oid = sc["order_id"]
    ctx: dict = {}
    if oid:
        ctx["order_id"] = oid
    query = tpl.format(oid=oid or "")
    return {
        "id": f"{prefix}-{n:03d}",
        "query": query.strip(),
        "user_id": user,
        "context": ctx,
        "expected_intent": "order_status",
        "expected_outcome": sc["outcome"],
        "expected_tools": sc["tools"],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def main() -> None:
    returns = _expand("ret", RETURN_SCENARIOS, _return_case)
    exchanges = _expand("exc", EXCHANGE_SCENARIOS, _exchange_case)
    wismo = _expand("wis", WISMO_SCENARIOS, _wismo_case)
    write_jsonl(OUT / "returns.jsonl", returns)
    write_jsonl(OUT / "exchanges.jsonl", exchanges)
    write_jsonl(OUT / "wismo.jsonl", wismo)
    print(f"wrote {len(returns)} returns, {len(exchanges)} exchanges, {len(wismo)} wismo -> {OUT}")


if __name__ == "__main__":
    main()
