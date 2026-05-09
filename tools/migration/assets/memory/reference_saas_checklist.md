---
name: SaaS Production Checklist (Reddit)
description: 6-point checklist for taking AI-built prototypes to production-ready SaaS — from a fractional CTO who rescues vibe-coded apps
type: reference
---

Source: Reddit r/replit post by Living-Pin5868 (fractional CTO, 50+ apps shipped), March 2026.

## The 6 Points

### 1. Write a PRD before you prompt
- 1-2 page doc specifying exactly what to build before touching any AI tool
- Define: who uses it, what actions they take, what each state looks like (empty/loading/error/success), edge cases, what NOT to build
- Without it: agent makes 50 product decisions for you, half wrong, then you spend days patching

### 2. Learn just enough version control
- Git saves snapshots; if agent breaks something, roll back instantly
- Branches: main (live), staging (test), feature branches per change
- Commits: save often with meaningful messages
- Merge only after testing on staging
- Without it: agent breaks checkout flow, no way to undo, users affected

### 3. Treat your database like it's sacred
- Use migrations (instruction files that say "add this column") — reversible, saved in Git
- Two databases: staging (test kitchen) and production (dining room)
- Every schema change hits staging first with realistic data volume (hundreds/thousands of rows, not 3)
- Never edit production database directly through Supabase/phpMyAdmin
- Example: add "discount percentage" field → staging shows null crashes frontend → fix on staging → apply clean to production

### 4. Optimize before users feel the pain
- **N+1 queries**: 200 invoices each fetching customer = 201 DB requests. Fix: eager loading (fetch all in one shot)
- **Infinite lists**: 15 test rows load fine, 4,000 real rows freezes browser. Fix: pagination (20 per page, every list, no exceptions)
- **Slow dashboards**: calculating totals on every load. Fix: caching (calculate once, store 5-10 min)
- Speed is trust. Slow app = side project feel. Users churn over speed even if features work

### 5. Write tests
- **Unit tests**: check math/logic ("$1000 + 12% tax = $1120")
- **Integration tests**: features work with real data, permissions enforced
- **E2E tests**: critical flows (signup → trial → create invoice → upgrade to paid)
- Tell agent in PRD to generate them. Run before every deploy
- Without tests: every new feature is a coin flip on breaking something else

### 6. Get beta testers, shut up, and listen
- 5-10 beta users matching target customer (not friends, not developers)
- Free access for a month in exchange for honest feedback
- Screen-share sessions — watch them use it
- Ask specific questions: "Walk me through creating your first invoice. Where did you get stuck?" not "What do you think?"
- Iterate fast: hear feedback Monday, ship improvements by Thursday
- Convert testers into paying customers by making them feel the product evolving

## Our Status Against This Checklist
1. PRD → Brief workflow (more rigorous: context, source material, rollback, numbered tests) ✓
2. Git → Both repos, commit per brief ✓
3. Database → SQLite WAL, migrations in state_registry ✓ (but no staging DB yet — dry run mode is partial coverage)
4. Optimize → Not stress-tested at scale yet. Worth doing before real clients
5. Tests → 100+ tests across briefs ✓
6. Beta testers → Two real estate agents interested. This is the priority gap
