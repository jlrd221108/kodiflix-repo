import json

import xbmc


def force_expert_settings_level():
    xbmc.executeJSONRPC(json.dumps({
        "jsonrpc": "2.0",
        "method": "Settings.SetSettingValue",
        "params": {
            "setting": "general.settinglevel",
            "value": 3
        },
        "id": 1
    }))


if __name__ == "__main__":
    force_expert_settings_level()
