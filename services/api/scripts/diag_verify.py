"""Throwaway diagnostic: shows what the model returns for ONE verification call, using the same
settings as the backend (services/api/.env). Prints no secrets. Delete after use; do not commit."""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inkloom_verify.prompts import verification as prompt  # noqa: E402
from inkloom_verify.prompts.loader import load_prompt  # noqa: E402
from inkloom_verify.providers.base import JsonCompletionRequest  # noqa: E402
from inkloom_verify.providers.openrouter import OpenRouterProvider  # noqa: E402
from inkloom_verify.verification import VerificationConfig, _ModelOutput  # noqa: E402

provider = OpenRouterProvider.from_env()
cfg = VerificationConfig()
system = load_prompt("verification", cfg.prompt_version).text
request = JsonCompletionRequest(
    system=system,
    user=prompt.user_message(
        "Our Standard plan costs $49 per month.",
        [("P1", "The Standard plan costs $59 per month.")],
    ),
    schema_name="claim_verification",
    json_schema=prompt.OUTPUT_SCHEMA,
    max_output_tokens=cfg.max_output_tokens,
)
completion = provider.complete_json(request)
print("model that answered:", completion.model)
print("reply keys:", sorted(completion.data.keys()))
print("reply:", json.dumps(completion.data)[:900])
try:
    _ModelOutput.model_validate(completion.data)
    print("RESULT: reply is VALID")
except Exception as error:  # noqa: BLE001
    print("RESULT: reply is INVALID ->", str(error)[:900])
