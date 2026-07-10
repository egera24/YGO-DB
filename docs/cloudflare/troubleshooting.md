# Troubleshoot rate limiting rules (snapshot)

> **Canonical:** https://developers.cloudflare.com/waf/rate-limiting-rules/troubleshooting/  
> **Snapshot date:** 2026-06-23

## Workers subrequests counted separately

Cloudflare may count Workers subrequests on the same zone as separate requests when **Also apply rate limiting to cached assets** is false. Exclude same-zone subrequests with:

```
and (cf.worker.upstream_zone == "" or cf.worker.upstream_zone != "<YOUR_ZONE>")
```

## Rate limiting rules with hostname conditions and Origin Rules

If Origin Rules rewrite the `Host` header and the rate limiting rule uses `http.host` in its counting expression, the rule may match in the request phase but fail to increment in the response phase. Fix by removing `http.host` from the counting expression or matching the rewritten hostname.

## Rate limiting fail-open behavior

Cloudflare rate limiting operates in **fail-open mode** during infrastructure overload — counters may be skipped rather than blocking legitimate traffic. There is no customer-visible signal for fail-open events.

## Per-data-center counting

Rate limiting counters are maintained per Cloudflare data center. Traffic distributed across many data centers may keep per-data-center rates below the threshold even when aggregate rate exceeds it. Consider this when setting thresholds for globally distributed traffic.

## Visitor blocked from a website

If you received Error 1015 or HTTP 429 while browsing or scraping, see:

- [Error 1015](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/)
- [Error 429](error-429.md)
- [Cardmarket recovery steps](README.md#recovery-after-ip-ban) in this repo
