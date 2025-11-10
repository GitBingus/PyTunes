import json
import os


USERDATA_FILE = "user.json"


def getUserData():
    """Load and return the user's data from disk, or False if not found/invalid."""
    if not os.path.exists(USERDATA_FILE):
        return False

    try:
        with open(USERDATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        
        elif isinstance(data, dict):
            return [data]
        
        else:
            return False
    except Exception as e:
        print(f"[getUserData] Error reading user data: {e}")
        return False


def setUserData(data):
    """Overwrite user data completely (used only when explicitly resetting all data)."""
    try:
        with open(USERDATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[setUserData] Error saving data: {e}")
        return False


def addUserData(new_data):
    """
    Safely merge new data into existing user data.
    Does NOT overwrite existing playlists, songs, or settings.
    """

    # Load existing data
    existing = getUserData()
    if not existing:
        # If no data exists yet, start fresh
        user_data = [{}]
    else:
        user_data = existing

    user = user_data[0]

    # Ensure all major keys exist
    for key in ("songs", "playlists", "settings"):
        if key not in user:
            user[key] = {} if key in ("songs", "playlists", "settings") else ""

    # --- Merge new data safely ---
    for key, value in new_data.items():
        # Playlists
        if key == "playlists":
            if not isinstance(user["playlists"], dict):
                user["playlists"] = {}
            # Merge new playlists
            if isinstance(value, dict):
                # Handle single-playlist dicts (with 'name' inside)
                if "name" in value and "songs" in value:
                    playlist_name = value["name"]
                    playlist_exists = any(
                        pl.get("name") == playlist_name for pl in user["playlists"].values()
                    )
                    if not playlist_exists:
                        pl_id = f"playlist{len(user['playlists']) + 1}"
                        user["playlists"][pl_id] = value
                else:
                    # Merge multiple playlists
                    for k, v in value.items():
                        if k not in user["playlists"]:
                            user["playlists"][k] = v

        # Songs
        elif key == "songs":
            if not isinstance(user["songs"], dict):
                user["songs"] = {}
            if isinstance(value, dict):
                user["songs"].update(value)

        # Settings
        elif key == "settings":
            if not isinstance(user["settings"], dict):
                user["settings"] = {}
            if isinstance(value, dict):
                user["settings"].update(value)

        else:
            user[key] = value

    # Save the merged data
    setUserData(user_data)
    return True