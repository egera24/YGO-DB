# Rate limiting rules (snapshot)

> **Canonical:** https://developers.cloudflare.com/waf/rate-limiting-rules/  
> **Snapshot date:** 2026-06-23

## Overview

Rate limiting rules allow you to define rate limits for requests matching an expression, and the action to perform when those limits are reached. Use rate limiting rules to prevent abuse — for example, to protect a login endpoint from brute-force attacks or to cap how many API calls a single client can make in a given time window.

If you were blocked as a visitor, see [Error 1015 documentation](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/).

## Rule parameters

Like other rules evaluated by Cloudflare's Ruleset Engine, rate limiting rules have:

- **Expression** — criteria for matching traffic (Rules language).
- **Action** — what to perform when the rate reaches the limit (e.g. Block, Managed Challenge).

Additional parameters:

| Parameter | Description |
|-----------|-------------|
| **Characteristics** | How Cloudflare tracks the rate (e.g. IP, cookie, header) |
| **Period** | Time window in seconds |
| **Requests per period** | Threshold that triggers the rule |
| **Duration** (mitigation timeout) | How long the action applies after the limit is hit |
| **Action behavior** | By default, action applies for the full duration regardless of request rate during mitigation |

Supported mitigation timeout values include: 10s, 60s, 300s, 600s, **3600s (1 h)**, 86400s (1 day). See canonical docs for the full list.

## Important remarks

- Rules are evaluated in order; some actions like *Block* stop evaluation of other rules.
- Rate limiting is **not** designed to allow a precise number of requests through; counters may lag by a few seconds.
- Counters are **per Cloudflare data center** (with exceptions for colocated DCs in the same geography).

## Availability (summary)

Counting by **IP** is available on Free plan and above. Advanced characteristics (cookie, JA3 fingerprint, JSON body fields) require higher plans.

See the [full availability table](https://developers.cloudflare.com/waf/rate-limiting-rules/#availability) in the canonical docs.
