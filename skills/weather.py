import json
import urllib.request
import urllib.parse

SKILL = {
    "name": "weather",
    "description": "查询任意城市的当前天气和未来预报",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "查询指定城市的天气情况和未来预报。使用 wttr.in 免费 API，无需 key。支持中英文城市名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，支持中英文，例如「上海」「Beijing」「Tokyo」",
                    },
                    "days": {
                        "type": "integer",
                        "description": "预报天数 1-3，默认 1（仅今天）",
                    },
                },
                "required": ["city"],
            },
        },
    }

def run(args: dict) -> str:
    city = args.get("city", "").strip()
    days = min(max(int(args.get("days", 1)), 1), 3)

    if not city:
        return "错误：请提供城市名称"

    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"天气查询失败：{e}"

    cur = data["current_condition"][0]
    desc = cur.get("lang_zh", [{}])[0].get("value") or cur["weatherDesc"][0]["value"]

    lines = [
        f"📍 {city} 当前天气",
        f"🌡 {cur['temp_C']}°C  体感 {cur['FeelsLikeC']}°C",
        f"☁  {desc}",
        f"💧 湿度 {cur['humidity']}%   🌬 风速 {cur['windspeedKmph']} km/h",
    ]

    if days > 1:
        lines.append("")
        for day in data["weather"][:days]:
            day_desc = day["hourly"][4].get("lang_zh", [{}])[0].get("value") \
                       or day["hourly"][4]["weatherDesc"][0]["value"]
            lines.append(
                f"📅 {day['date']}  {day['mintempC']}~{day['maxtempC']}°C  {day_desc}"
            )

    return "\n".join(lines)
