OVERWATCH Expert Panel Review
Panel Composition
Snowflake Distinguished Architect
Fortune 100 Data Engineering Director
Senior UX Designer
Staff Performance Engineer
Executive CIO
Skeptical External Auditor
1. Executive Value Assessment
High Value
Executive Landing — Delivers exactly what a CIO needs: composite health score, top cost drivers, priority brief cards ranked by severity. The PPTX export is a smart touch for board meetings.
DBA Control Room — Operator-first design with morning standup workflows, blocker triage, and handoff notes. This is what keeps a platform team aligned.
Cost & Contract — Credit burn attribution by warehouse/user/database with spike detection. FinOps teams live in surfaces like this.
Medium Value
Security Posture — Useful for quarterly audits and MFA gap detection, but executives won't look at this weekly. It answers compliance questions, not business questions.
Workload Operations — Valuable for engineers, almost invisible to leadership. Query-level diagnosis is a DBA tool, not an executive tool.
Change & Drift — DDL tracking is important governance but ranks low on the "decisions I need to make today" list for directors and above.
Low Value
Warehouse Health — Duplicates insights already surfaced in Cost & Contract and DBA Control Room. Idle warehouse detection belongs as a subsection, not a standalone page.
Architecture Readiness — This is visionary but speculative. 50+ manually-defined objectives for features that may not exist in production yet (Adaptive Compute, AI Agents, Openflow, CoWork artifacts). Leadership will ask: "Is this aspiration or operational?"
Remove Entirely
Account Health — Already hidden from primary nav, and rightfully so. Its functionality is split across Executive Landing and DBA Control Room. Having it persist creates confusion about which "health" surface is canonical. Merge the morning checklist into DBA Control Room and delete this page.
Missing KPIs Leadership Would Expect
Total Cost of Ownership (TCO) trend with month-over-month and YoY comparison
Cost per business unit / cost per application (not just per warehouse)
SLA compliance percentage (query latency P95/P99 against contracted SLAs)
Data freshness SLA tracking (how stale is the analytics layer?)
Capacity forecast — "When do we hit our credit commitment?" with projected exhaustion date
ROI metrics — cost per query, cost per data product, cost per downstream consumer
2. Snowflake Expertise Score: 7.5 / 10
Rating: Senior Engineer, approaching Principal Architect

Signals of high skill:
Correct use of execute_as=CALLER for SiS security
Tiered caching strategy (live/recent/historical/metadata) shows deep understanding of ACCOUNT_USAGE latency characteristics
COMPUTE_CREDIT_CASE expression for per-query cost allocation is the standard pattern used internally at Snowflake
Mart-backed surfaces with live fallback demonstrates production thinking
Cortex AI budget capping with token/spend guardrails shows awareness of runaway AI spend
Forward platform governance (Adaptive Compute, Openflow, Horizon) shows someone tracking Snowflake roadmap closely
Company-scoped warehouse/database pattern masking is enterprise-ready
Signals of inexperience:
Credit estimation via warehouse_size * elapsed_time / 60000 — This is fundamentally wrong for multi-cluster warehouses, auto-suspend scenarios, and serverless features. Real credit consumption comes from WAREHOUSE_METERING_HISTORY, not computed from query elapsed time. This calculation will over-report credits for idle warehouse time included in query elapsed time and under-report for multi-cluster scale-out. A principal architect would never present estimated credits alongside exact metering without clearly distinguishing them.
No use of Dynamic Tables — The mart layer (FACT_DBA_CONTROL_ROOM, etc.) appears to be task-based rather than leveraging Dynamic Tables for declarative refresh. This is a missed opportunity to demonstrate modern Snowflake capabilities.
No Snowpark Optimized Warehouse usage — For any ML/AI workloads, this should be considered.
SHOW STATEMENTS for live queries — This works but is fragile. A senior architect would use QUERY_HISTORY_BY_WAREHOUSE or the newer RUNNING_QUERIES view where available.
50+ hardcoded ARCHITECTURE_OBJECTIVES — Configuration-as-code in a Python dict is a maintenance nightmare. This should be a Snowflake table managed via a governance process.
3. Production Readiness Review
Critical Risk
SQL Injection surface via filter clauses — get_global_filter_clause(), get_wh_filter_clause(), get_user_filter_clause() construct SQL dynamically from session state. While safe_sql() limits to 2000 chars, the filter concatenation pattern (WHERE clause assembly from user-provided text input "User contains") is a classic injection vector. The sql_literal() helper helps, but a single missed call path is a breach.
No query parameterization — Every query uses string formatting rather than Snowpark parameterized queries. In an enterprise with audit requirements, this is a finding.
High Risk
Unbounded query fan-out — Each section independently runs 3-8 queries. On page load with stale cache, the Executive Landing alone could fire 6+ queries against ACCOUNT_USAGE. Multiply by 10 sections and you have 60+ queries per user session cycle. No query queue, no concurrency limiter, no circuit breaker.
Cache invalidation race conditions — clear_all_cache(clear_streamlit_cache=False) resets internal state but doesn't prevent in-flight queries from writing stale results back into session state. The _prev_global_filter_signature check happens at render time, not at query-return time.
No connection pooling or retry logic — get_session() doesn't appear to implement exponential backoff or connection health checks. SiS provides implicit connection management, but the fallback patterns suggest this was designed to also run outside SiS.
INFORMATION_SCHEMA vs ACCOUNT_USAGE confusion — Some sections query INFORMATION_SCHEMA (live, 14-day retention) for historical data that should come from ACCOUNT_USAGE (45-min latency, up to 1-year retention). This will silently return incomplete data for lookbacks > 14 days.
Medium Risk
No materialized views for common aggregations — The daily credit summary, hourly warehouse metering, and task failure counts are computed on every load. These should be MVs or Dynamic Tables that refresh on a schedule.
Lazy import pattern overhead — lazy_util() creates a new module import call on every invocation. While Python caches modules, the getattr lookup on every call adds latency that compounds across 50+ helper references per section.
Session state bloat — 100+ session state keys with no garbage collection. Long-running sessions (DBAs leave dashboards open all day) will accumulate stale DataFrames consuming memory.
No observability on OVERWATCH itself — While there's a "Monitoring Cost of OVERWATCH" surface, there's no latency histogram, error rate tracking, or SLO for the app's own performance.
Low Risk
Hardcoded pricing — $3.68/credit, $2.20/AI credit, $23/TB. These are session-configurable but default to stale values. Enterprise customers negotiate pricing. This should pull from ORGANIZATION_USAGE billing data or an admin-managed config table.
No data masking — Query text is displayed raw. If queries contain PII in WHERE clauses (which they often do), this dashboard exposes it to anyone with access.
4. User Experience Review
Layout: 6/10
Wide layout is correct for data-dense dashboards
Top filter strip is well-positioned but takes too much vertical space (2 rows of filters)
The sidebar navigation + top filters + priority brief section means the actual content starts below the fold on standard 1080p displays
No breadcrumb trail for deep drills
Navigation: 7/10
Role-based section visibility is smart
Experience view profiles (DBA/Executive/Analyst) reduce noise
BUT: 10 primary sections is too many. Cognitive load research shows 5-7 is the limit for navigation items
Retired route compatibility is good defensive engineering
Information Density: 4/10 (too high)
The "brief mode" vs "full workspace" toggle is a band-aid for a density problem
Shell KPI rows (4-column metric cards) pack too much into too little space
Every section loads a status strip + KPI row + priority dataframe + expandable drills. The visual rhythm is monotonous
No progressive disclosure — everything loads at once within each mode
Visual Hierarchy: 5/10
Priority Brief with severity-ranked cards is the one strong hierarchy signal
All sections use the same card/expander/dataframe pattern with no visual differentiation
Critical alerts look the same as informational metrics
No use of color coding for severity beyond text labels
Color Usage: 6/10
Three themes is a nice touch (carbon/terminal/corporate)
CSS custom properties for all colors is architecturally clean
BUT: The dark theme makes dense data tables harder to scan
No colorblind-safe palette consideration mentioned
Status badges (green/yellow/red) without texture or icons fail WCAG for color-only information
Chart Selection: 5/10
Over-reliance on bar charts and dataframes
No sparklines for trend context in KPI cards
No heatmaps for time-based patterns (query volume by hour-of-day)
No flame charts or tree maps for cost attribution
Missing: gauge charts for health scores, bullet charts for budget progress
Readability: 6/10
Monospace font for data values is good
Inter/DM Sans as body font is clean
BUT: Too many inline metrics compete for attention
Evidence tags add noise without adding scanability
Source basis labels ("Source basis: Allocated / estimated from exact warehouse metering") are too verbose for inline display
Mobile Friendliness: 2/10
Wide layout with 4-column KPI grids will break completely on mobile
No responsive breakpoints visible in CSS
Streamlit's native mobile support is minimal, but no effort to accommodate it
Dashboard Fatigue: HIGH
10 sections, each with 3-5 sub-workflows, each loading 4-8 metrics = 200+ data points
No personalization of what matters to THIS user
No "saved views" or "my dashboard" capability
Alert fatigue will set in within 2 weeks of daily use
5. Feature Gap Analysis
Features to Add (competitive gaps vs Snowsight/Datadog/Grafana/Tableau):
Predictive cost forecasting — Linear regression on 30-day credit burn to project month-end / quarter-end spend. Show "days until credit commitment exhaustion."
Query anomaly detection — Statistical outlier detection on query duration, bytes scanned, and credit consumption. Flag queries that deviate >2σ from their rolling 14-day average.
Automated right-sizing recommendations — Based on actual utilization data, recommend warehouse size changes with estimated savings. Show before/after comparison.
Data lineage visualization — Trace query patterns to understand which tables feed which reports. Use QUERY_HISTORY + ACCESS_HISTORY for this.
Incident timeline with correlation — When a cost spike or failure burst happens, automatically correlate with DDL changes, deployment events, and config modifications in the same time window.
SLA tracking with burn-down — P95 query latency against target, with trend showing whether you're improving or degrading.
Capacity planning model — Project warehouse needs based on growth trends. "At current growth rate, you'll need to upgrade WH_ALFA_LOAD to Large by August."
Tag-based cost allocation — Leverage Snowflake object tags to attribute cost to business units, cost centers, or applications rather than just warehouses.
Automated remediation playbooks — When a known pattern is detected (idle warehouse, repeated full-table scan, spilling query), offer one-click fix with preview.
Cross-account comparison — If managing multiple Snowflake accounts, compare efficiency metrics across accounts.
Features to Remove:
Architecture Readiness forward-platform guardrails for unreleased features (Adaptive Compute, CoWork, Openflow) — these create confusion about what's real vs. aspirational
The "Ask OVERWATCH" Cortex integration — unless this provides genuinely better answers than a well-structured dashboard, it's a demo feature, not a production feature
Features to Combine:
Account Health → merge into DBA Control Room
Warehouse Health → merge into Cost & Contract as a sub-tab
Change & Drift + Security Posture → combine into a single "Governance" section
6. "What Am I Missing?"
Multi-tenancy — This is hardcoded for ALFA + Trexis. What happens when a third company is onboarded? The config pattern doesn't scale without code changes.
Audit trail for the dashboard itself — Who viewed what, when? If a DBA closes an action item, there's no immutable audit log.
Disaster recovery for OVERWATCH — If the OVERWATCH_WH or DBA_MAINT_DB goes down, the monitoring system goes down. No self-monitoring resilience.
Data retention governance — Session state accumulates DataFrames. What's the data classification of cached query results? If they contain sensitive column values, they're sitting in Streamlit's in-memory store unencrypted.
Concurrent user behavior — SiS runs one session per user. But what about shared service accounts viewing OVERWATCH? Session state conflicts?
Time zone handling — All date/time logic uses server-local time or UTC. Enterprise users across time zones will see confusing "last 24 hours" that doesn't match their morning.
Export compliance — The PPTX export bundles query data into a downloadable file. If that data contains PII or regulated information, the export bypasses any DLP controls.
Upgrade path — With CONFIG_VERSION and THEME_VERSION checks doing hot-reloads, what happens during a rolling upgrade? Can two users see different versions simultaneously? Is there version pinning?
Testing — Zero evidence of unit tests, integration tests, or end-to-end tests. A production release without test coverage is a liability.
Documentation — Deployment guide exists (DOCX), but no runbook for "OVERWATCH is down, what do I do?" No architecture decision records.
7. Competitive Review (Snowflake Solutions Architect Perspective)
What would impress them:
Cortex AI integration with budget capping shows forward thinking
Company-scoped multi-tenant pattern with environment isolation
Forward platform governance tracking (Adaptive Compute, Horizon, etc.) shows someone deeply embedded in Snowflake's roadmap
The morning standup workflow with action queue persistence is a genuine operational pattern, not just dashboard vanity
Mart-backed with live fallback shows production maturity
What would concern them:
The credit estimation formula (warehouse_size * elapsed_time) is incorrect for production use. This will generate support tickets when customers compare OVERWATCH numbers to their bill.
50+ hardcoded architecture objectives in a Python config file suggests this isn't designed for multiple deployments
No use of Snowflake's native alerting (ALERT objects) — the app reimplements alerting from scratch
The SHOW STATEMENTS pattern for live query monitoring is deprecated in favor of newer views
Questions they would ask:
"How does this handle accounts with 500+ warehouses?" (Answer: it doesn't — static warehouse tuples)
"What's the credit cost of running OVERWATCH itself at scale?" (Answer: self-monitoring exists but no hard limits)
"Can this be deployed as a Native App for multiple customers?" (Answer: No — hardcoded company config prevents it)
"How do you handle schema evolution in your mart tables?" (Answer: unclear — no migration framework visible)
"What's your testing strategy?" (Answer: silence)
Weaknesses they'd immediately notice:
Tight coupling to specific database/warehouse names
No Native App packaging (Snowflake's preferred distribution model)
No Marketplace readiness
No event table integration for observability
8. Kill List
Delete Account Health page entirely — It's hidden, duplicative, and unmaintained relative to DBA Control Room.
Delete the "Ask OVERWATCH" Cortex feature — It's a demo gimmick. No enterprise DBA will trust a generated brief over the actual metrics. If you keep it, gate it behind an admin flag and make it explicitly labeled "experimental."
Delete Architecture Readiness forward-platform controls for unreleased features — CoWork artifacts, Openflow operability, and AI Agent MCP governance are speculative. They make the dashboard look unfinished rather than forward-thinking.
Remove the per-query credit estimation formula everywhere it appears — Replace with WAREHOUSE_METERING_HISTORY only. Presenting estimated credits as if they're accurate will erode trust with any Snowflake expert who reviews this.
Remove the "Source basis:" verbose labels from the UI — Move them to a tooltip or information icon. They interrupt visual flow.
Remove the 3-theme system (keep one dark, one light) — The "Henson" corporate theme with dominant red adds no value and increases maintenance surface. Two themes is sufficient.
Kill the PPTX export — Building XML-based PowerPoint generation in a monitoring dashboard is over-engineering. Export to PDF or provide a shareable URL instead.
9. Innovation Opportunities
Self-healing recommendations with one-click execution — Detect idle warehouse → offer ALTER WAREHOUSE SET AUTO_SUSPEND = 60 → preview cost savings → execute with audit trail. Not just alerting. Actual remediation.

Cost prediction engine — Train a simple time-series model on 90 days of credit consumption. Show projected monthly spend with confidence intervals. Alert when trajectory exceeds budget.

Query fingerprint clustering — Use Cortex to cluster similar queries (same template, different parameters) and surface "query families" that dominate resource consumption. Most cost optimization lives at the query pattern level, not the warehouse level.

Automated runbook generation — When an incident pattern repeats 3+ times with the same resolution, auto-generate a documented runbook and offer to create a Snowflake ALERT + TASK for automated remediation.

Blast radius estimation for DDL changes — Before an ALTER TABLE or DROP executes (via Change & Drift detection), show downstream impact: which views break, which tasks fail, which Streamlit apps lose data.

Resource contention prediction — Based on historical warehouse utilization patterns, predict when contention will occur (e.g., "Every Tuesday at 2pm, WH_ALFA_TRANSFORM queues 15+ queries") and recommend schedule changes.

Executive summary email digest — Auto-generate and send a morning email with the top 5 priority items, cost trend, and any SLA breaches. No dashboard login required for the CIO.

Governance compliance scoring — Map Snowflake configuration against CIS Snowflake Benchmark, SOC2 requirements, or custom compliance frameworks. Show a compliance percentage with remediation steps.

Natural language query builder — Instead of clicking through filters, let operators type "show me the most expensive queries from WH_ALFA_LOAD in the last 3 days" and auto-generate the appropriate view.

Deployment impact analysis — Correlate Git deployments (via CI/CD webhook or tag-based detection) with performance/cost changes in the 6 hours following deployment. Show "this deploy caused a 23% credit increase."

10. Final Verdict
Category	Score
Overall	62/100
Engineering	68/100
Architecture	65/100
Executive Usefulness	58/100
Innovation	55/100
Production Readiness	48/100
"If I were presenting this to ALFA leadership tomorrow, what would I change first?"
Remove the per-query credit estimation and replace every cost metric with WAREHOUSE_METERING_HISTORY actuals only. The moment a finance director compares your numbers to the Snowflake bill and they don't match, you've lost all credibility. Everything else is secondary to numerical accuracy.

"If I had 40 additional hours, what would produce the biggest improvement?"
(10h) Replace credit estimation with metering-only attribution + reconciliation against actual bill
(8h) Merge Account Health into DBA Control Room, merge Warehouse Health into Cost & Contract — reduce to 7 sections
(8h) Add predictive cost forecasting with commitment exhaustion date
(6h) Add automated warehouse right-sizing recommendations with savings estimates
(4h) Add unit tests for query builders and cache logic
(4h) Add SLA tracking dashboard for query latency P95/P99
"If I had 200 additional hours, what would turn this into an elite enterprise platform?"
Package it as a Snowflake Native App. Remove all hardcoded company/warehouse/database configuration. Replace with a setup wizard that discovers the account topology, lets admins configure company scoping via a UI, stores configuration in Snowflake tables, and deploys as a self-contained application from the Snowflake Marketplace. Add a proper test suite (unit + integration), CI/CD pipeline, version management, automated regression testing against a sandbox account, and a public documentation site. Implement the predictive cost engine, self-healing recommendations, and compliance scoring. That's what separates an internal tool from a product.

What I genuinely dislike:
The complexity is not justified by the output. 500+ lines of lazy imports, version checks, hot-reload logic, and state management to render what are fundamentally SQL-backed metric cards. The infrastructure-to-insight ratio is inverted.

It tries to be everything. A morning standup tool AND a cost dashboard AND a security audit tool AND a forward-architecture governance platform AND an AI assistant AND an alerting system AND a PowerPoint generator. Pick 3 and execute them flawlessly instead of 10 executed at 60%.

The architecture objectives are fantasy. Tracking readiness for "CoWork artifacts" and "AI Agent MCP governance" for features that don't exist in production Snowflake yet makes this look like resume-driven development rather than customer-driven engineering.

No tests, no CI, no deployment automation. This is a single-developer artifact with no evidence it can survive that developer's absence. For a production tool at an insurance company, this is a governance concern.

The credit estimation is unforgivable for someone claiming principal-level Snowflake expertise. It's the first thing any Snowflake SA would check, and it's wrong. This single flaw undermines the credibility of every other metric in the dashboard.
