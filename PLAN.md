# TrueMatch — Product Roadmap

Mission: Verified jobs globally + AI-written applications + honest, HR-grade odds & coaching. Free forever.

## Principles
1. Every industry, not just tech
2. Odds calibrated to real industry expectations
3. Advice is concrete — specific moves with lift %-values
4. Free — no paywalls
5. Global: Africa, Middle East, Australia, remote/hybrid/physical

---

## PHASE A — Real odds + multi-industry jobs (ACTIVE)
A1. Registry expansion — Africa, Middle East, Australia (test candidates, keep only tokens returning >0)
A2. Multi-signal odds engine (app/odds.py)
    Signals: skill_coverage, years_experience, career_trajectory, company_stage_fit,
             seniority_match, resume_strength, education_match, apply_timing,
             competition_proxy, referral_potential
    Each returns: value, weight, contribution, reason
A3. Advice v2 engine
    Output: odds_pct, why (top helps/hurts), boosters[{action, lift_pct, why, effort, cost}],
            free_plan[7 days], outreach_script
A4. UI: job.html (big odds card, why, boosters w/ lift chips, plan accordion),
         dashboard.html (odds badge + top booster preview)
A5. Deploy

## PHASE B — Resume strength + career trajectory
B1. resume_strength.py: length, quantification %, action verbs, section completeness,
    ATS-friendliness, date format, gaps > 6mo, seniority signals
B2. career_trajectory.py: infer role ladder from past titles
B3. Feed both into odds engine

## PHASE C — More ATS sources
C1. Workday (banks, retail, healthcare, gov, universities)
C2. SmartRecruiters
C3. SuccessFactors (SAP enterprise)
C4. BambooHR (SMEs)

## PHASE D — Calibration with real data
D1. Track application -> response -> interview -> offer funnel
D2. Calibrate odds per company/seniority/region
D3. Bayesian update from outcomes

## PHASE E — Personalized coaching
E1. AI resume rewrite per job
E2. Interview prep (questions + STAR stories)
E3. Outreach script (LinkedIn/email to hiring manager)
E4. Follow-up reminders

## PHASE F — Quality of life
F1. Filters: region / industry / remote type
F2. Saved searches + alerts
F3. Daily/weekly digest email
F4. Application tracker dashboard

## PHASE G — Scale
G1. Multi-language
G2. Salary transparency
G3. Company review layer
G4. Referral network

---

## Current state (update as we go)
- Jobs: ~9,700 in Aiven (Greenhouse/Ashby/Lever)
- Deployed: truematch-plum.vercel.app
- Latest commit: c4ea8d5
- Pending: Phase A1 (registry expansion)
