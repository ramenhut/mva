import json, os, shutil, sys, urllib.request

system = f"You are a self-modifying CLI agent on unix. Script: {os.path.abspath(__file__)} Dir: {os.path.dirname(os.path.abspath(__file__))}. Respond concisely. Use self_update only when changes to your code are needed. Always preserve: tool interface, backup logic, main loop. Explain changes before applying them.\nCurrent source:\n```\n{open(os.path.abspath(__file__)).read()}\n```"
history = [{"role": "user", "content": "Add methods to: save/load history for recovery, and summarize history via LLM when >500k tokens. Reorganize as needed."}]
tools = [{"type": "function", "name": "self_update", "description": "Overwrite this script with new code. Validates syntax, backs up old version.", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}]

def self_update(code):
    try: # Verify the code is valid before applying it.
        compile(code, os.path.abspath(__file__), "exec")
    except SyntaxError as e:
        return f"REJECTED: {e}"
    shutil.copy2(os.path.abspath(__file__), os.path.abspath(__file__) + ".bak")
    with open(os.path.abspath(__file__), "w") as f:
        f.write(code)
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

while True:
    while True: # Initial run will build out minimum required capabilities.
        output = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.openai.com/v1/responses", json.dumps({"model": "gpt-5-mini", "instructions": system, "input": history, "tools": tools}).encode(), {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})).read()).get("output", [])
        print("\n".join(p["text"] for o in output if o.get("type") == "message" for p in o.get("content", []) if p.get("type") == "output_text"), end="")
        history.extend(output)
        calls = [i for i in output if i.get("type") == "function_call"]
        if not calls: break
        for fc in calls:
            r = self_update(json.loads(fc["arguments"])["code"]) if fc["name"] == "self_update" else "Unknown tool"
            history.append({"type": "function_call_output", "call_id": fc["call_id"], "output": r})
    try: # Allow the user to contribute.
        inp = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if inp:
        history.append({"role": "user", "content": inp})
