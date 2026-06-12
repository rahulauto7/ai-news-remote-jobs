# User Profile — Daily AI Jobs Matching

Source-of-truth for the profile-aware Jobs section in the daily PDF. Read by
`tools/job_match.py` to rank `.tmp/jobs.json` against this profile. Edit this
file (no code change required) to retune what surfaces tomorrow.

**Format rules for the parser** (keep these or matching breaks):
- Skills: one bullet per weight, `- Weight N: term, term, ...`
- Exclusions: one bullet per category, `- Seniority: ...` / `- Geo: ...` / `- Tech: ...`
- Target roles: one bullet per role title.

## Target roles

Apply to titles that look like these. Senior / lead / principal / staff /
manager / director / VP / chief / head-of are dropped by the Exclusions below.

- AI Automation Engineer
- n8n Developer
- Workflow Automation Engineer
- AI Implementation Specialist
- Voice AI Developer
- Conversational AI Developer
- AI Agent Engineer
- AI Solutions Engineer
- RevOps Automation
- AI Chatbot Developer
- No-Code AI Developer
- AI Integration Engineer
- Forward Deployed Engineer

## Skills (rank-weighted)

- Weight 3: n8n, voiceflow, relevance ai, claude code, ai agents, mcp, ai automation, workflow automation, ai agent
- Weight 2: rag, langchain, langgraph, vector db, embeddings, prompt engineering, ai workflow, crewai, autogen, devin, cursor, openai, anthropic, llm, agentic
- Weight 1: python, javascript, typescript, rest api, webhooks, zapier, make.com, integromat, crm, siebel, oracle crm, salesforce, hubspot

## Hard exclusions (drop the job entirely if any token matches)

- Seniority: senior, sr., lead, principal, staff, manager, director, head of, vp, vice president, chief, architect
- Geo: us only, usa only, us residents, us-based, us based, must be based in us, must reside in us, (us), (usa), americas only, north america only, eu only, europe only, uk only, apac only, asia only, canada only, australia only, india only
- Tech: data scientist, ml researcher, research scientist, mlops, devops, sre, hardware, embedded, robotics engineer, nlp researcher

## Geo & employment type

- Geo: worldwide remote (anywhere / global / worldwide / remote). Drop region-locked listings.
- Employment type: full-time, part-time, contract, freelance, internship — all welcome.
- Visa sponsorship: not required (the user is in India, hiring from anywhere).

## Why I'm a strong fit (used in summary line — not for matching)

- 9-10 months hands-on AI automation: shipped n8n workflows, Voiceflow agents, Relevance AI flows, and Claude Code agentic systems.
- 2 portfolio projects shipped: Defense Contract Analyzer (PDF -> risky clauses + risk score, submitted to a hackathon) and this AI News Pipeline (daily 20-section PDF).
- 2.5 years enterprise CRM at Indian Oil Corporation Ltd. (Siebel / Oracle CRM workflows since 2023-12-12). Rare combination: enterprise CRM operator + modern AI agent builder. Strong fit for AI-in-CRM, RevOps automation, AI sales tooling.
- Time zone: India (UTC+5:30). Comfortable with async-first global remote teams; available for some EU and US overlap hours.
