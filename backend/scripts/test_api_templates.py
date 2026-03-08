import asyncio
import aiohttp
import json

async def test_api():
    """Test notification templates API"""
    url = "http://localhost:8000/api/v1/notifications/templates"

    # You'll need to get a valid token first
    # For now, let's just try without auth to see the error
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                print(f"Status: {response.status}")
                data = await response.json()
                print(f"\nResponse keys: {data.keys()}")

                if 'templates' in data and len(data['templates']) > 0:
                    print(f"\nTotal templates: {len(data['templates'])}")

                    # Check single_leg_alert specifically
                    single_leg = next((t for t in data['templates'] if t['template_key'] == 'single_leg_alert'), None)
                    if single_leg:
                        print("\nSingle leg alert template:")
                        print(f"  template_key: {single_leg.get('template_key')}")
                        print(f"  popup_title_template: {single_leg.get('popup_title_template', '[NOT IN RESPONSE]')}")
                        print(f"  popup_content_template: {single_leg.get('popup_content_template', '[NOT IN RESPONSE]')}")
                        print(f"  alert_sound_file: {single_leg.get('alert_sound_file', '[NOT IN RESPONSE]')}")
                        print(f"  alert_sound_repeat: {single_leg.get('alert_sound_repeat', '[NOT IN RESPONSE]')}")

                    # Show first template structure
                    print("\nFirst template structure:")
                    print(json.dumps(data['templates'][0], indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_api())
