from pathlib import Path

path = Path(__file__).resolve().parent.parent / ".env"
text = path.read_text(encoding="utf-8") if path.exists() else ""
updates = {
    "LLM_ENABLED": "1",
    "LLM_ADVISOR_ENABLED": "1",
    "LLM_PRIMARY_ENABLED": "1",
    "LLM_SECONDARY_ENABLED": "1",
}
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        out.append(f'{key}="{updates[key]}"')
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}="{value}"')
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("enabled: " + ", ".join(updates))
