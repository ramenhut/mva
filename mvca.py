import json, os, re, subprocess, sys, threading, urllib.request

WHITE, GRAY, GREEN, RESET = "\033[97m", "\033[90m", "\033[32m", "\033[0m"
DIR = os.path.dirname(os.path.abspath(__file__))

def _sanitize_name(name):
    name = re.sub(r'[<>:"/\\|?*]', '', name).strip('. ')
    return re.sub(r'\s+', ' ', name)[:64] or "cell"

def _setup_identity():
    raw = input(f"{WHITE}Hello, what is my name? {RESET}").strip()
    return _sanitize_name(raw) if raw else "cell"

def _build_system(name):
    return f"You are {name}, a persistent coding assistant running as a REPL. You can read, write, and execute files in your working directory. Think step by step, then act. # Memory Your conversation history is automatically compacted when it grows too large. Store important persistent details (architecture decisions, key file paths, project conventions, user preferences) in a `CLAUDETTE.md` file in the project directory so they survive compaction. # Environment You are running within a *nix based environment, so you have access to common commands like find, grep. You must ask the user for permission before accessing their system or connecting to any other system (e.g. browsing the web), but you are capable of downloading, installing, and running programs directly. # Working Directory Your working directory is your home — all relative paths in tools resolve here. Place all code, tools, artwork, data, and project files directly in your working directory (or in subfolders within it). Narrate each step to the user with a short message BEFORE executing it, so they can follow along. # Dependency Management When you need external packages: 1. Python packages: Create a venv if one doesn't exist (run_command('python3 -m venv .venv')), then install with run_command('.venv/bin/pip install <package>'). Use longer timeouts for installs (e.g. timeout: 300). 2. System packages: Use brew install on macOS (run_command('brew install <package>', timeout: 300)). Ask the user for permission first. 3. Track dependencies: Add them to a requirements.txt. 4. Run scripts through their venv python: run_command('.venv/bin/python app.py'). To access system resources: write_file accepts absolute paths (e.g. /etc/hosts) for access outside your working directory. Use run_command to interact with the OS. You can request elevated permissions via sudo if the user approves."

TOOLS = [
    {"type": "function", "name": "write_file", "description": "Create or overwrite a file. Paths are relative to the project directory unless absolute.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"type": "function", "name": "run_command", "description": "Run a shell command in the project directory and return output. Use timeout for long-running commands like package installs.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "description": "Max seconds to wait (default 30). Use 300+ for installs."}}, "required": ["command"]}},
]

class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    def __init__(self, label="", color=GREEN):
        self._label, self._color, self._stop = label, color, threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
    def _spin(self):
        i = 0
        while not self._stop.is_set():
            print(f"\r{self._color}  {self.FRAMES[i % len(self.FRAMES)]} {self._label}{RESET}", end="", flush=True)
            i += 1
            self._stop.wait(0.08)
        print(f"\r{' ' * (len(self._label) + 6)}\r", end="", flush=True)
    def __enter__(self):
        self._thread.start(); return self
    def __exit__(self, *_):
        self._stop.set(); self._thread.join()

WORK_DIR = HISTORY_FILE = SYSTEM = None
MAX_HISTORY_TOKENS = 100_000

def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(WORK_DIR, path)

def execute_tool(name, args):
    if name == "write_file":
        p = _resolve(args["path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(args["content"])
        return "OK"
    elif name == "run_command":
        proc = subprocess.Popen(args["command"], shell=True, cwd=WORK_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        try:
            for line in proc.stdout:
                print(f"{GRAY}    {line}{RESET}", end="", flush=True)
                lines.append(line)
            proc.wait(timeout=args.get("timeout", 30))
        except subprocess.TimeoutExpired:
            proc.kill(); lines.append("\n[timed out]")
        return "".join(lines).strip()
    return "Unknown tool"

def call_llm_stream(input_items, api_key, instructions):
    body = {"model": "gpt-5-mini", "instructions": instructions, "input": input_items, "tools": TOOLS, "stream": True}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    event_name = None
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: ") and event_name:
            yield event_name, json.loads(line[6:])
            event_name = None

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def _repair_history(history):
    call_ids = {i.get("call_id") for i in history if isinstance(i, dict) and i.get("type") == "function_call"}
    result_ids = {i.get("call_id") for i in history if isinstance(i, dict) and i.get("type") == "function_call_output"}
    orphaned = call_ids - result_ids
    if not orphaned:
        return False
    while history:
        item = history[-1]
        if not isinstance(item, dict) or (item.get("type") in ("function_call", "function_call_output") and item.get("call_id") in orphaned):
            history.pop()
        else:
            break
    return True

def _extract_text(history):
    lines = []
    for item in history:
        if not isinstance(item, dict): continue
        role, typ = item.get("role"), item.get("type")
        if role == "user":
            lines.append(f"User: {item.get('content', '')}")
        elif typ == "message":
            lines += [f"Assistant: {p.get('text', '')}" for p in item.get("content", []) if isinstance(p, dict) and p.get("type") == "output_text"]
        elif typ == "function_call":
            lines.append(f"Tool: {item.get('name', '')}({item.get('arguments', '')})")
        elif typ == "function_call_output":
            lines.append(f"Result: {item.get('output', '')[:500]}")
    return "\n".join(lines)

def _emergency_compact(history, api_key):
    print(f"{GREEN}  ⚠ Context too large, compacting history...{RESET}")
    text = _extract_text(history)[-50000:]
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps({
        "model": "gpt-5-mini",
        "instructions": "Produce a thorough, detailed summary of this conversation. Preserve key decisions, file paths, project state, and important context.",
        "input": [{"role": "user", "content": text}],
    }).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(req).read().decode())
    summary = "".join(p.get("text", "") for i in result.get("output", []) if i.get("type") == "message" for p in i.get("content", []) if isinstance(p, dict) and p.get("type") == "output_text")
    history[:] = [{"role": "user", "content": f"[Summary of previous conversation]\n{summary}"}]
    save_history(history)

def _build_instructions():
    instructions = SYSTEM
    claudette_path = os.path.join(WORK_DIR, "CLAUDETTE.md")
    if os.path.isfile(claudette_path):
        with open(claudette_path) as f:
            instructions += "\n\n# Project Notes\n" + f.read()
    return instructions

def react_loop(history, api_key):
    while True:
        if len(json.dumps(history)) // 4 > MAX_HISTORY_TOKENS:
            _emergency_compact(history, api_key)
        calls, output, printed_text = [], [], False
        print()
        thinking = Spinner("thinking", color=GRAY)
        thinking.__enter__()
        for event, data in call_llm_stream(history, api_key, _build_instructions()):
            if event == "response.output_text.delta":
                if thinking: thinking.__exit__(); thinking = None
                print(f"{GRAY}{data['delta']}{RESET}", end="", flush=True)
                printed_text = True
            elif event == "response.completed":
                if thinking: thinking.__exit__(); thinking = None
                output = data.get("response", {}).get("output", [])
        if thinking: thinking.__exit__()
        if printed_text: print()
        calls = [i for i in output if i.get("type") == "function_call"]
        history.extend(output)
        save_history(history)
        if not calls: return
        for fc in calls:
            name, args = fc["name"], json.loads(fc["arguments"])
            print(f"{GREEN}  🔧 [tool: {name}({json.dumps(args)})]{RESET}")
            try: result = execute_tool(name, args)
            except Exception as e: result = f"Error: {e}"
            history.append({"type": "function_call_output", "call_id": fc["call_id"], "output": result})
        save_history(history)

def main():
    global WORK_DIR, HISTORY_FILE, SYSTEM
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key: print("Set OPENAI_API_KEY environment variable."); sys.exit(1)
    name = _setup_identity()
    WORK_DIR = os.path.join(DIR, name)
    os.makedirs(WORK_DIR, exist_ok=True)
    HISTORY_FILE = os.path.join(WORK_DIR, "history.json")
    SYSTEM = _build_system(name)
    try:
        with open(HISTORY_FILE) as f: history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): history = []
    if _repair_history(history):
        save_history(history); print(f"{GRAY}(repaired incomplete history){RESET}")
    print(f"{GRAY}I am {name}.{RESET}")
    print("I remember our conversation. What's next?" if history else "What should I grow into?")
    while True:
        try:
            user_input = input(f"\n{WHITE}> ").strip()
            print(RESET, end="")
        except (EOFError, KeyboardInterrupt): print(); break
        if not user_input: continue
        history.append({"role": "user", "content": user_input})
        save_history(history)
        try: react_loop(history, api_key)
        except Exception as e:
            import traceback
            print(f"{GREEN}  ⚠ Error: {e}{RESET}")
            history.append({"role": "user", "content": f"[SYSTEM ERROR during react loop — {type(e).__name__}: {e}]\n\n{traceback.format_exc()}\n\nPlease investigate and fix the issue."})
            save_history(history)

if __name__ == "__main__":
    try: main()
    except Exception as e: import traceback; print(f"\033[32m  ⚠ Fatal error: {e}\033[0m"); traceback.print_exc()
