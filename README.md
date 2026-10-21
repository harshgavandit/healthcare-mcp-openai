# Healthcare Explorer

[Open the app](https://healthcare-mcp-openai.vercel.app)

Healthcare Explorer is a demo app for browsing patient records and asking questions about them. It includes 10 sample patients with visit histories, diagnoses, medications, and lab results.

You can:

- Search the patient directory and open a patient's profile.
- View a risk summary based on chronic conditions, active medications, and abnormal lab results.
- Check visits in the last 30, 90, and 180 days, the most recent discharge, and recurring diagnoses.
- Browse the database tables, columns, and record counts.
- Ask the AI assistant questions about the demo records and see which tools it used to answer. The assistant requires an access code.

The assistant uses OpenAI to explain results retrieved through MCP tools. The tools can also be used by compatible MCP clients to read patient summaries, inspect the schema, and run read-only SQL queries.

All patient records in the web app are generated demo data. Risk levels come from predefined scoring rules and are not medical advice or validated clinical predictions.
