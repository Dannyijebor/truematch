import asyncio, sys
from app.ingestion.adapters import ADAPTERS

# Candidates: Africa, Middle East, Australia. Non-tech and tech, all industries.
CANDIDATES = [
    # --- Africa (tech, fintech, health, mobility, ecommerce) ---
    ("greenhouse", "flutterwave"),
    ("greenhouse", "paystack"),
    ("greenhouse", "andela"),
    ("greenhouse", "m-kopa"),
    ("greenhouse", "sunking"),
    ("greenhouse", "mPharma"),
    ("greenhouse", "chippercash"),
    ("greenhouse", "wave"),
    ("greenhouse", "jumia"),
    ("greenhouse", "kuda"),
    ("greenhouse", "opay"),
    ("greenhouse", "moniepoint"),
    ("greenhouse", "paga"),
    ("greenhouse", "autochek"),
    ("greenhouse", "maxng"),
    ("greenhouse", "moove"),
    ("lever", "yoco"),
    ("lever", "takealot"),
    ("lever", "piggyvest"),
    ("lever", "fairmoney"),
    ("ashby", "lemfi"),
    ("ashby", "risevest"),
    ("ashby", "bamboo"),
    ("ashby", "nomba"),
    ("workable", "twiga"),
    ("workable", "turaco"),
    ("workable", "reliancehmo"),
    ("workable", "heliumhealth"),
    ("workable", "54gene"),

    # --- Middle East (UAE, Saudi, Qatar) ---
    ("greenhouse", "careem"),
    ("greenhouse", "talabat"),
    ("greenhouse", "kitopi"),
    ("greenhouse", "noon"),
    ("greenhouse", "propertyfinder"),
    ("greenhouse", "bayut"),
    ("greenhouse", "hala"),
    ("lever", "tabby"),
    ("lever", "tamara"),
    ("lever", "foodics"),
    ("lever", "salla"),
    ("lever", "unifonic"),
    ("ashby", "sarwa"),
    ("ashby", "huspy"),
    ("ashby", "rain"),
    ("workable", "yap"),

    # --- Australia / NZ ---
    ("greenhouse", "airwallex"),
    ("greenhouse", "linktree"),
    ("greenhouse", "immutable"),
    ("greenhouse", "cultureamp"),
    ("greenhouse", "safetyculture"),
    ("greenhouse", "employmenthero"),
    ("lever", "xero"),
    ("lever", "deputy"),
    ("lever", "petcircle"),
    ("lever", "eucalyptus"),
    ("lever", "healthengine"),
    ("ashby", "employmenthero"),
    ("workable", "envato"),
    ("workable", "airtasker"),
    ("workable", "seek"),

    # --- Global remote-first, non-tech verticals ---
    ("greenhouse", "doist"),
    ("greenhouse", "automattic"),
    ("greenhouse", "buffer"),
    ("greenhouse", "zapier"),
    ("lever", "remote"),
    ("lever", "toptal"),
    ("lever", "andela"),
    ("ashby", "deel"),
    ("ashby", "remotecom"),
]

async def try_one(source, token):
    try:
        fn = ADAPTERS[source]
        jobs = await fn(token)
        return (source, token, len(jobs), None)
    except Exception as e:
        return (source, token, 0, type(e).__name__)

async def main():
    sem = asyncio.Semaphore(4)
    async def wrapped(s, t):
        async with sem:
            return await try_one(s, t)
    results = await asyncio.gather(*[wrapped(s, t) for s, t in CANDIDATES])

    winners, dead = [], []
    for s, t, n, err in results:
        if n > 0:
            winners.append((s, t, n))
            print(f"  OK    {s}/{t}: {n}")
        else:
            dead.append((s, t, err))
            print(f"  --    {s}/{t}: {err or '0 jobs'}")

    print(f"\n=== {len(winners)} WORKING, {len(dead)} dead ===")
    print("\nMerge these into registry.py:\n")
    for s, t, n in winners:
        print(f'    ("{s}", "{t}"),  # {n}')

if __name__ == "__main__":
    asyncio.run(main())
