"""Throwaway diagnostic (do not commit): print the provider's first 429 reply, then stop."""
import runpy, sys
sys.path.insert(0, "src")
from inkloom_verify.providers import openrouter as o

orig = o.OpenRouterProvider._error


def show(self, response, payload, model):
    code = response.status_code
    if code == 429 or (isinstance(payload, dict) and isinstance(payload.get("error"), dict) and payload["error"].get("code") == 429):
        print("STATUS", code)
        print("HEADERS", {k: v for k, v in response.headers.items() if k.lower().startswith(("retry", "x-ratelimit"))})
        print("BODY", response.text[:800])
        raise SystemExit(1)
    return orig(self, response, payload, model)


o.OpenRouterProvider._error = show
sys.argv = ["run_eval.py", "--verdicts", "openrouter", "--pipeline", "full", "--dataset", "eval/dev_only.jsonl"]
print("diagnostic started", flush=True)
runpy.run_path("eval/run_eval.py", run_name="__main__")
