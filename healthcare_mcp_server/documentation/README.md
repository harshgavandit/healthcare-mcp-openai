# Healthcare MCP Server

For the current OpenAI configuration, local commands and verification results,
see the [workspace README](../../README.md). This document retains the original
MCP tutorial; the running server now defaults to `127.0.0.1`, query limits are
bounded to 1–500, and the existing database should not be reseeded during setup.

A remote MCP (Model Context Protocol) server that exposes healthcare patient record tools to AI agents. Built with Python, SQLite, and the MCP Python SDK using Streamable HTTP transport.

---

## Project Structure

```
healthcare-mcp-server/
├── patients.db          # SQLite database (auto-generated on first run)
├── seed_data.py         # Populates the database with 10 sample patients
├── db.py                # Database connection utility
├── tools/
│   ├── risk_summary.py  # Tool 1A: Patient risk scoring
│   ├── readmission.py   # Tool 1B: Readmission risk analysis
│   ├── schema_tool.py   # Tool 2A: Database schema introspection
│   └── query_tool.py    # Tool 2B: Safe SQL query execution
├── server.py            # MCP server — registers tools and starts Streamable HTTP
├── requirements.txt     # Python dependencies
└── README.md
```

---

## Available Tools

| Tool | Input | Description |
|------|-------|-------------|
| `patient_risk_summary` | `patient_id` | Computes a LOW / MEDIUM / HIGH risk tier from diagnoses, medications, and labs |
| `readmission_insights` | `patient_id` | Analyzes visit history for readmission risk with a plain-English summary |
| `database_schema` | _(none)_ | Returns all table schemas — useful before writing SQL queries |
| `query_database` | `sql_query`, `max_rows` | Executes any SELECT query against patients.db (write operations are blocked) |

---

## Prerequisites

- Python 3.10 or higher
- [ngrok](https://ngrok.com) account and CLI (free tier is sufficient) — needed to expose the local server over HTTPS for Claude Desktop
- [Claude Desktop](https://claude.ai/download) installed

---

## Setup

### Step 1 — Clone or download the project

```bash
cd healthcare-mcp-server
```

### Step 2 — Create a Python virtual environment

```bash
python -m venv venv
```

Activate it:

```bash
# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

You should see `(venv)` at the start of your terminal prompt.

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create the database and seed sample data

```bash
python seed_data.py
```

Expected output:

```
All tables created successfully.
=== Seed complete. Row counts ===
  patients       : 10 rows
  visits         : 32 rows
  diagnoses      : 44 rows
  medications    : 39 rows
  lab_results    : 48 rows
```

This creates `patients.db` in the project folder with 10 realistic patients — diabetic patients, cardiac patients, elderly patients with multiple conditions, and one healthy baseline patient.

---

## Running and Testing

### Step 5 — Test each tool independently (If you want to)

Each tool can be run as a plain Python script before starting the MCP server. This confirms the business logic works before adding the network layer.

```bash
python tools/risk_summary.py   # Should print HIGH risk for patients 1 and 4, LOW for patient 8
python tools/readmission.py    # Should print recurring diagnoses and risk levels
python tools/schema_tool.py    # Should print all 5 tables with column definitions
python tools/query_tool.py     # Should show query results and a rejected DELETE attempt
```

### Step 6 — Start the MCP server

```bash
python server.py
```

Expected output:

```
Starting Healthcare MCP Server on http://0.0.0.0:8000/mcp
INFO:     Started server process [...]
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The server is now running locally at `http://localhost:8000/mcp`.

### Step 7 — Test with MCP Inspector (optional but recommended)

MCP Inspector is a browser-based tool for testing MCP servers directly.

Open `https://inspector.tools.mcp.run` in your browser.

1. Set the transport to **Streamable HTTP**
2. Enter the URL: `http://localhost:8000/mcp`
3. Click **Connect**
4. Go to the **Tools** tab — all 4 tools should be listed
5. Select `patient_risk_summary`, enter `patient_id: 4`, click **Run Tool**

You should see James Walker's HIGH-risk profile in the response panel.

---

## Exposing the Server over HTTPS with ngrok

Claude Desktop requires a **public HTTPS URL** — it cannot connect to a plain `http://localhost` address. We use ngrok to create a secure tunnel from a public HTTPS endpoint to our local server.

### Step 8 — Install ngrok

**macOS (Homebrew):**
```bash
brew install ngrok
```

**Windows / Linux:** Download the installer from [https://ngrok.com/download](https://ngrok.com/download) and follow the instructions.

### Step 9 — Authenticate ngrok (one-time setup)

Sign up at [https://ngrok.com](https://ngrok.com) (free), then copy your auth token from the dashboard and run:

```bash
ngrok config add-authtoken YOUR_AUTH_TOKEN
```

### Step 10 — Start the ngrok tunnel

With the MCP server already running on port 8000 (from Step 6), open a **new terminal window** and run:

```bash
ngrok http 8000
```

ngrok will display output like this:

```
Forwarding   https://a1b2-203-0-113-42.ngrok-free.app -> http://localhost:8000
```

Copy the `https://...ngrok-free.app` URL — you will need it in the next step.

> **Note:** The ngrok URL changes every time you restart ngrok on the free tier. You will need to update your Claude Desktop config each session unless you have a paid ngrok account with a static domain.

---

## Connecting Claude Desktop

### Step 11 — Find the Claude Desktop config file

| Platform | Config file location |
|----------|----------------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

### Step 12 — Add the MCP server

Open the config file in any text editor and add the `mcpServers` block. Replace the URL with your actual ngrok URL from Step 10.

```json
{
  "mcpServers": {
    "my-healthcare-server": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8000/mcp"
      ]
    }
  }
}
```

If the file already has other MCP servers configured, add the `"healthcare"` entry inside the existing `"mcpServers"` object.

### Step 13 — Restart Claude Desktop

Fully quit and reopen Claude Desktop. You should see a tools/hammer icon in the chat interface indicating connected MCP tools.

---

## Testing with Claude Desktop

Start a new conversation in Claude Desktop and try these prompts in order:

**Basic risk check:**
```
What is the risk profile for patient 4?
```

**Readmission risk:**
```
Is patient 1 at risk of being readmitted? Give me a clinical summary.
```

**Compare two patients:**
```
Compare the risk profiles of patient 4 and patient 8. Which one should the care team prioritize?
```

**Schema discovery + custom query:**
```
Look at the database schema and show me all patients who have more than 3 active medications.
```

**Natural language to SQL:**
```
Which patients have had an abnormal HbA1c result? List their names and values.
```

**Safety guardrail demo:**
```
Delete patient 8 from the database.
```
_(Claude will attempt the operation but the server will block it with: "Only SELECT statements are allowed.")_

---

## Sample Patients

| ID | Name | Age | Primary Conditions |
|----|------|-----|-------------------|
| 1 | Margaret Collins | 72F | CHF, Diabetes, Hypertension |
| 2 | Robert Nguyen | 65M | Coronary Artery Disease, Hypertension |
| 3 | Linda Patel | 58F | Diabetes, Chronic Kidney Disease |
| 4 | James Walker | 81M | COPD, Heart Failure — **highest risk** |
| 5 | Susan Martinez | 47F | Asthma, Anxiety |
| 6 | David Kim | 55M | Diabetes, Obesity |
| 7 | Barbara Thompson | 69F | Atrial Fibrillation, Stroke history |
| 8 | Charles Brown | 38M | Healthy — **low risk baseline** |
| 9 | Patricia Davis | 74F | Osteoporosis, Depression, Hypertension |
| 10 | Michael Johnson | 62M | Cancer in remission, Diabetes |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'mcp'`**
The virtual environment is not activated. Run `source venv/bin/activate` (macOS/Linux) or `venv\Scripts\activate` (Windows) before running any Python command.

**MCP Inspector shows "Connection refused"**
The server is not running. Make sure `python server.py` is running in another terminal.

**Claude Desktop does not show the tools icon**
- Check that the config file is valid JSON (no trailing commas)
- Make sure the ngrok tunnel is running and the URL in the config matches exactly (including `/mcp` at the end)
- Fully quit Claude Desktop (not just close the window) and reopen it

**ngrok URL stopped working**
The free tier ngrok URL expires when you stop the tunnel. Restart ngrok, copy the new URL, update the config file, and restart Claude Desktop.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp[cli]` | MCP Python SDK — `FastMCP` class, tool registration, Streamable HTTP transport |
| `uvicorn` | ASGI web server that serves the `/mcp` endpoint |
| `starlette` | Web framework used internally by FastMCP |
