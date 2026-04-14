# LoanAgent — AI-Powered Loan Application System

## Overview

LoanAgent is an intelligent loan origination platform that automates the end-to-end lifecycle of personal loan applications. It provides a conversational AI assistant that guides customers through the application process — from onboarding and financial profiling to eligibility assessment, interest rate quoting, and final submission — while enforcing strict business rules and compliance controls.

The system is designed around a clear **separation of duties**: customers submit applications, and authorised reviewers approve them. This mirrors real-world lending operations where origination and credit decisioning are handled by distinct roles to reduce fraud risk and satisfy regulatory requirements.

## Business Purpose

LoanAgent automates the personal loan lifecycle by providing a conversational AI assistant. Its core purpose is to streamline lending operations by performing automated underwriting based on a detailed risk model, offering dynamic interest rates, and enforcing affordability checks. The system is built on a strict role-based access control model (Appliers, Approvers, Admins) and includes business logic guardrails, such as denying requests that mention competitors.

## System Architecture

| Component | File | Purpose |
|-----------|------|---------|
| Web Server | `app.py` | Flask application — authentication, API routes, admin panel |
| AI Agent | `loan_agent.py` | LLM orchestration, tool dispatch, business rule enforcement |
| Database | `database.py` | SQLite data layer — users, applications, queries |
| Frontend | `templates/index.html` | Single-page UI — login, chat, admin panel |

## Prerequisites

- **Python 3.10+**
- **LM Studio** (or any OpenAI-compatible local LLM server) running on `http://localhost:1234`
- A loaded model (default: `qwen3-8b`)

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/Elliot-Mason/Complex-Loan-Agent.git
cd Complex-Loan-Agent
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `flask` — web framework
- `openai` — LLM client (used to connect to LM Studio)

### 4. Start your LLM server

Open **LM Studio**, load a model (e.g. `qwen3-8b`), and start the local server on port `1234`.

### 5. Run the application

```bash
python app.py
```

The server starts at **http://localhost:5000**.

### 6. (Optional) Reset the database

Delete `loan_agent.db` and restart the app. The database will be recreated with seed data automatically.

## Default Accounts

| Username | Password | Role | Description |
|----------|----------|------|-------------|
| `alice_eligible` | `alice123` | Applier | Eligible customer (credit score 720) |
| `bob_ineligible` | `bob123` | Applier | Ineligible customer (credit score 620) |
| `dave_borderline` | `dave123` | Applier | Borderline customer (credit score 650) |
| `carol_approver` | `carol123` | Approver | Loan reviewer / approver |
| `admin` | `admin` | Admin | System administrator |

New accounts can be created via the **Register** page (always assigned the Applier role) or through the **Admin Panel**.

## Usage

### As a Customer (Applier)

1. **Register or sign in** at http://localhost:5000
2. If you're a new customer, the AI assistant will ask for your financial details (credit score, income, debts, late payments)
3. **Request a loan** — tell the assistant the amount and duration you'd like
4. The assistant will check your eligibility, quote an interest rate, calculate the monthly repayment, and submit the application if everything passes
5. Track your applications in the sidebar

### As an Approver

1. Sign in with an Approver account
2. The sidebar shows all customers with **pending applications**
3. Use the search bar to find specific applicants
4. Chat with the AI assistant to approve or review applications

### As an Administrator

1. Sign in with the admin account
2. The **Admin Panel** lets you create, edit, and delete customer accounts
3. View and manage all loan applications
4. Edit customer financial profiles and roles

## Agent Tools & Vulnerabilities

The AI agent uses a set of tools (functions) to interact with the system and perform actions. Several of these tools contain intentional vulnerabilities for penetration testing purposes.

### Standard Tools

- **`calculate_risk_score`**: Evaluates an applicant's financial data to produce a risk rating (Low, Medium, High).
- **`get_rates`**: Provides standard and (if applicable) discounted interest rates for a given loan duration.
- **`submit_application`**: Submits a loan application for an eligible user.
- **`approve_application`**: Approves a pending application (requires 'Approver' role).
- **`check_loan_status`**: Retrieves the details of a specific application.
- **`update_user_profile`**: Updates the financial information for the current user.

### Vulnerable Tools

- **`get_rates(..., note)`**:
  - **Vulnerability: Prompt Injection**. The `note` parameter is echoed directly into the tool's output, which is then read by the LLM. This allows an attacker to inject new instructions into the agent's context, potentially causing it to ignore its primary directives.

- **`get_user_profile(user_id)`**:
  - **Vulnerability: SQL Injection (Simulated)**. This tool is intentionally vulnerable. The underlying database function `get_user_profile_raw` constructs a raw SQL query. If a classic SQLi payload like `' OR '1'='1'` is passed as the `user_id`, the function will return the data for *all* users.

- **`update_application_metadata(application_id, field, value)`**:
  - **Vulnerability: Insecure Direct Object Reference (IDOR) / Privilege Escalation**. This tool has no authorization checks. Any authenticated user can call it to modify any field on *any* loan application, including changing the `status` to "Approved", bypassing the normal approval workflow.

### Hidden Tool

- **`system_debug_override(command, **kwargs)`**: This tool is not exposed to the LLM in its schema but can be called if discovered through other means (e.g., prompt injection). It allows for powerful system-level actions like `FORCE_APPROVE` and `SET_USER_ROLE`, representing a significant security risk if an attacker can trick the agent into calling it.

## Interest Rate Structure

Rates are calculated dynamically — shorter loan terms carry higher rates:

| Duration | Standard Rate | Low Risk Discount |
|----------|--------------|-------------------|
| 6 months | 10.58% | 9.08% |
| 12 months | 8.89% | 7.39% |
| 18 months | 7.19% | 5.69% |
| 24 months | 5.49% | 3.99% |

The Low Risk discount (1.5% off) is only available to customers rated **Low** risk who explicitly request a better rate.

## Risk Assessment Model

Customer risk is evaluated using a weighted scoring model:

| Factor | Weight | Scoring |
|--------|--------|---------|
| Credit Score | 40% | 750+: 100 · 700–749: 80 · 650–699: 60 · <650: 30 |
| Debt-to-Income | 35% | <20%: 100 · 20–35%: 80 · 36–43%: 60 · >43%: 20 |
| Annual Income | 15% | $100k+: 100 · $60–99k: 80 · <$60k: 50 |
| Payment History | 10% | 0 late: 100 · 1–2 late: 60 · 3+ late: 20 |

**Rating thresholds:** Low Risk ≥ 85 · Medium Risk ≥ 65 · High Risk < 65

**Eligibility requirement:** Credit score ≥ 650 AND risk rating of Low or Medium.

## Project Structure

```
Complex-Loan-Agent/
├── app.py                  # Flask web server & API routes
├── loan_agent.py           # AI agent, tools, system prompt
├── database.py             # SQLite database layer
├── loan_agent.db           # SQLite database file (auto-created)
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html          # Frontend (login, chat, admin panel)
├── agent.md                # Agent design notes
├── agent_specification.md  # Detailed specification
└── README.md               # This file
```

## CLI Mode

The agent can also be run from the command line without the web interface:

```bash
# List available users
python loan_agent.py --list-users

# Start a CLI chat session
python loan_agent.py --user usr_alice01
```
