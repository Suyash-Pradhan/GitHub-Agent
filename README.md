# GitResolve AI: Autonomous Multi-Agent Pull Request Pipeline

An autonomous software engineering system built with **LangGraph** that takes a GitHub issue URL, investigates the repository codebase, designs a step-by-step fix plan, writes targeted code repairs along with verifying unit tests, and opens a Pull Request—all end-to-end and completely automated.

---

## 🛠️ Tech Stack & Key Technologies

- **Orchestration**: `LangGraph` (for building stateful, multi-agent workflows as a cyclic graph)
- **Large Language Model**: Google Gemini (`gemini-3.1-flash-lite` via `langchain-google-genai`)
- **Git & GitHub Integration**: `PyGithub` (for branching, committing, comparing, and PR creation)
- **Abstract Syntax Tree (AST) Parsing**: `tree-sitter` (for language-specific lazy symbol indexing)
- **Configuration & Environment**: `python-dotenv`
- **Testing Framework**: `pytest`

---

## 🏗️ Architecture & Control Flow

The workflow is modeled as a stateful `StateGraph` in LangGraph. State is shared globally via `AgentState` ([state.py](file:///d:/code/Github%20issue/state.py)), a `TypedDict` containing input context, intermediary artifacts (fix plans, logs, cached symbols), and final outputs.

```
       [Start] GITHUB_ISSUE_URL
                  │
                  ▼
         ┌─────────────────┐
         │   Code Reader   │ ◄─── (ReAct Loop, max 4 turns)
         │    (Agent 1)    │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │     Planner     │
         │    (Agent 2)    │
         └────────┬────────┘
                  │
          [route_by_complexity]
          /       |         \
   (simple)   (complex)   (error)
     /            |            \
    v             v             v
┌────────┐    ┌────────┐   ┌──────────────┐
│  Code  │    │  Code  │   │ Handle Error │
│ Writer │    │ Writer │   │   (Helper)   │
└─┬──────┘    └─┬──────┘   └────┬─────────┘
  │             │               │
  ▼             ▼               │
┌────────┐    ┌────────┐        │
│  Test  │    │  Test  │        │
│ Writer │    │ Writer │        │
└─┬──────┘    └─┬──────┘        │
  │             │               │
  ▼             ▼               │
┌────────┐    ┌────────┐        │
│   PR   │    │   PR   │        │
│ Opener │    │ Opener │        │
└─┬──────┘    └─┬──────┘        │
  │             │               │
  ▼             ▼               │
 [END] ◄────────┴───────────────┘
```

---

## 🤖 The 5-Agent Pipeline

### 1. Code Reader ([agents/code_reader.py](file:///d:/code/Github%20issue/agents/code_reader.py))
Responsible for investigating the repository to locate the buggy files and symbols.
- **Dynamic ReAct Loop**: Instead of standard agent tools that execute blindly, the Code Reader evaluates the codebase step-by-step over a dynamic loop (capped at 4 turns).
- **Batched Tool Execution**: In each turn, the agent can call multiple tools simultaneously (e.g., grepping multiple keywords or reading files) to minimize LLM call round-trips.
- **Lazy Symbol Parsing**: Uses `tree-sitter` parser dynamically for Python, JS, TS, and Go. It indexes local files only when grep flags them, caching the parsed symbols (`symbol_cache`) in `AgentState`.
- **Targeted Line Reading**: Using cached symbols, it requests specific line ranges via `read_lines()` instead of dumping large files into the prompt context, avoiding context window bloat.
- **Race Condition Protection**: The agent's final report (`report_findings`) is restricted; the loop rejects it if it is batched with exploratory tools. This prevents the agent from generating a stale summary based on tools executed in the same turn.

### 2. Planner ([agents/planner.py](file:///d:/code/Github%20issue/agents/planner.py))
Consumes the issue definition and the Code Reader's context to produce a formal fix design.
- Generates a structured JSON plan specifying the files to edit, the exact steps, and a complexity classification (`simple` or `complex`).
- **Dynamic Graph Routing**: The complexity output drives LangGraph's conditional routing function `route_by_complexity`. Currently, both paths route to the Code Writer, but the graph is pre-engineered to support advanced agent logic or human-in-the-loop review nodes for complex issues.

### 3. Code Writer ([agents/code_writer_agent.py](file:///d:/code/Github%20issue/agents/code_writer_agent.py))
Implements the fix specified in the planner's design.
- Infers target programming languages and extension formats dynamically.
- Generates targeted code modifications, returning them formatted under clear `FILE: <filepath>` markers.

### 4. Test Writer ([agents/test_writer_agent.py](file:///d:/code/Github%20issue/agents/test_writer_agent.py))
Responsible for producing test code using `pytest` to guarantee quality.
- Focuses on writing tests that reproduce the original bug (failing prior to the fix) and validating the fix along with standard edge cases.
- Emits the test script under the `FILE: tests/test_generated_fix.py` identifier.

### 5. PR Opener ([agents/pr_opener_agent.py](file:///d:/code/Github%20issue/agents/pr_opener_agent.py))
Pushes the modifications to GitHub and creates the Pull Request.
- Creates a dedicated branch named `fix/issue-auto-<sanitized-title>-<uuid>`.
- Extracts changed file blocks and the generated unit tests, committing them via PyGithub.
- Generates a detailed PR description containing the issue context, the agent's plan, the patch, and the tests, then opens the Pull Request.

---

## 🎯 Technical Design Highlights (Interviewer FAQ)

- **Why LangGraph over LangChain Chains?**
  LangGraph provides cyclic graph capabilities, enabling real-world workflows (like ReAct loops and conditional fallback routing) that require loops and state persistence. This design isolates each agent's execution while sharing context through a single, well-defined state schema.
- **State Isolation & Handlers**:
  Agents only interact with the shared `AgentState` object. They do not invoke other agents directly. This decouples logic, makes each node unit-testable, and allows easy swap-ins of individual LLMs or prompts.
- **Lazy Parsing & Caching**:
  Rather than parsing the entire codebase at the beginning, files are only parsed for AST symbols after a keyword match. Symbol coordinates are cached in `AgentState` across turns, avoiding redundant API calls and processing overhead.
- **Strict Context Capping**:
  Limits include a 4-turn ReAct ceiling and a 6KB char limit for file reads (truncated with instructions to use targeted range queries). This ensures API costs and response latency remain low and highly predictable.

---

## 📂 Project Structure

```
├── agents/
│   ├── code_reader.py         # Agent 1: ReAct investigation loop & symbol parsing
│   ├── planner.py             # Agent 2: Plan construction & complexity routing
│   ├── code_writer_agent.py   # Agent 3: Targeted source code patch generation
│   ├── test_writer_agent.py   # Agent 4: pytest generation matching the patch
│   ├── pr_opener_agent.py     # Agent 5: Git branch commits & GitHub PR publishing
│   └── handle_error.py        # Helper: Gracefully records pipeline failures
├── utils/
│   ├── repo_tools.py          # Tool logic (list_dir, grep, read_lines, symbol walk)
│   ├── commit.py              # PyGithub wrapper for updates and new files
│   ├── parser.py              # Matches FILE block markers in agent responses
│   └── llm_res_formater.py    # Extracts text content from LangChain messages
├── state.py                   # Global AgentState TypedDict and MODEL_NAME definition
├── main.py                    # Graph assembly, GitHub issue fetching, and CLI entry point
├── .env.example               # Template for system keys
└── requirements.txt           # Python application dependencies
```

---

## ⚙️ Setup & Installation

### 1. Clone & Configure Workspace
```bash
git clone https://github.com/Suyash-Pradhan/Github-agent-Test.git
cd Github-agent-Test

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install core requirements
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the template environment file:
```bash
cp .env.example .env
```
Open `.env` and fill in the parameters:
```env
GITHUB_TOKEN=your_github_fine_grained_access_token
GOOGLE_API_KEY=your_google_gemini_api_key
```

### 🔑 GitHub Fine-Grained Token Setup
To read issues, write changes, and open PRs, create a Fine-Grained Personal Access Token with:
1. **Repository access**: "Only select repositories" (or "All repositories")
2. **Repository Permissions**:
   - `Contents`: Read and Write (to write code, tests, and push branches)
   - `Pull Requests`: Read and Write (to open Pull Requests)
   - `Issues`: Read-only (to fetch the issue description)

---

## 🚀 Running the Pipeline

To run the pipeline on any public repository issue (providing your GitHub token has access), pass the URL to the CLI:

```bash
python main.py --issue-url https://github.com/owner/repository/issues/105
```

---

## ⚠️ Real-World Limitations

- **Symbol Parsing Support**: Tree-sitter AST symbol extraction is optimized for Python, JavaScript, TypeScript, and Go. Other source files gracefully fall back to regex keyword search (`grep`).
- **Unit Test Execution**: Generated test suites are written in Python (`pytest`). For non-Python codebases, the tests are valuable logic verification templates but are not executed natively by the pipeline's runners.
- **Complex Repository Layouts**: Large monorepos or issues spanning multiple separate code directories may hit the 4-turn safety cap before resolving files.

---

## 🗺️ Roadmap & Next Steps
- **Human-in-the-Loop Approval**: Route the `complex` complexity branch to a CLI/UI prompt requesting human verification before triggering Code Writer.
- **Web Interface**: A lightweight web frontend showing the real-time node transitions of the LangGraph execution path.
- **Retrieval-Augmented Generation (RAG)**: Fallback search indexing using vector embeddings of code snippets when exact keyword matching fails.
