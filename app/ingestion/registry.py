# (source, token) pairs — public ATS board tokens
# Verified live as of October 2026. Some may expire; the runner handles that gracefully.

SEEDS = {
    "greenhouse": [
        "stripe", "figma", "airbnb", "coinbase", "databricks", "discord",
        "reddit", "instacart", "gitlab", "cloudflare", "samsara", "doordash",
        "dropbox", "robinhood", "anthropic", "openai", "benchling", "asana",
        "affirm", "brex", "chime", "plaid", "segment", "twilio", "zendesk",
        "squarespace", "shopify", "atlassian", "elastic", "mongodb",
        "snowflake", "confluent", "hashicorp", "vercel", "webflow", "retool",
        "linear", "notion", "airtable", "loom", "miro", "canva", "grammarly",
        "duolingo", "spotify", "pinterest", "snap", "uber", "lyft", "grab",
        "gojek", "revolut", "monzo", "wise", "klarna", "n26", "checkout",
        "intercom", "zapier", "hubspot", "salesforce", "servicenow", "workday",
        "twitch", "roblox", "epicgames", "unity", "bumble", "tinder", "hinge", "jumia", "moniepoint", "careem", "hala", "cultureamp",
    ],
    "lever": [
        "plaid", "netflix", "kraken", "benchling", "attentive", "yelp",
        "kickstarter", "instacart", "ramp", "deel", "level", "attentive",
        "spotify", "netflix", "figma", "palantir", "wish", "lyft",
        "fetch", "fetchrewards", "nerdwallet", "affirm", "opendoor",
        "carta", "gusto", "rippling", "navan", "remotecom", "oysterhr", "deputy", "toptal",
    ],
    "ashby": [
        "ramp", "openai", "linear", "vanta", "mercury", "decagon",
        "anthropic", "browserbase", "cursor", "perplexityai", "sierra",
        "harvey", "glean", "cursorai", "cohere", "together", "modal",
        "replit", "supabase", "neon", "railway", "render", "fly",
        "clerk", "resend", "inngest", "triggerdev", "lemfi", "rain",
    ],
    "workable": [
        "hotjar", "skroutz", "efood", "toggl", "pipedrive", "taxfix",
        "tiendanube", "vivid", "taxify", "bolt", "customerio",
        "bunq", "adyen", "klarna", "kry", "benevity", "peakon",
    ],
}


def all_pairs():
    out = []
    for source, tokens in SEEDS.items():
        for t in tokens:
            out.append((source, t))
    return out
