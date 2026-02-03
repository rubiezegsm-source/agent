from flask import Flask, request, jsonify
import requests

# ---------------------------------------
# KONFIGURACJA PAMIĘCI (Apps Script)
# ---------------------------------------
WEBAPP_URL = "https://script.google.com/macros/s/AKfycbyPNzgEED6YmbmLCDdHQqMUny-jE6ZXskF6NTIiOswbfmD5w6u5uTKULHceLRsFlmAfwg/exec"


def call_memory_api(action, **kwargs):
    payload = {"action": action}
    payload.update(kwargs)
    response = requests.post(WEBAPP_URL, json=payload)
    return response.json()

# ---------------------------------------
# OPERACJE NA PLIKACH
# ---------------------------------------

def memory_create(name, content):
    return call_memory_api("create", name=name, content=content)

def memory_read(file_id):
    return call_memory_api("read", fileId=file_id)

def memory_update(file_id, content):
    return call_memory_api("update", fileId=file_id, content=content)

def memory_delete(file_id):
    return call_memory_api("delete", fileId=file_id)

def memory_list():
    return call_memory_api("list")

# ---------------------------------------
# OPERACJE NA FOLDERACH
# ---------------------------------------

def memory_create_folder(name):
    return call_memory_api("create_folder", name=name)

def memory_list_folders():
    return call_memory_api("list_folders")

def memory_create_in_folder(folder_id, name, content):
    return call_memory_api("create_in_folder", folderId=folder_id, name=name, content=content)

def memory_list_in_folder(folder_id):
    return call_memory_api("list_in_folder", folderId=folder_id)

# ---------------------------------------
# POMOCNICZE FUNKCJE DO WYSZUKIWANIA
# ---------------------------------------

def find_folder_by_name(folder_name):
    folders = memory_list_folders()
    if folders.get("status") != "ok":
        return None, folders
    for f in folders.get("folders", []):
        if f.get("name") == folder_name:
            return f, None
    return None, {"status": "error", "message": f"Nie znaleziono folderu: {folder_name}"}

def list_files_in_folder_by_name(folder_name):
    folder, err = find_folder_by_name(folder_name)
    if err:
        return err
    return memory_list_in_folder(folder["id"])

def find_file_in_folder_by_name(folder_name, file_name):
    folder, err = find_folder_by_name(folder_name)
    if err:
        return None, err
    files = memory_list_in_folder(folder["id"])
    if files.get("status") != "ok":
        return None, files
    for f in files.get("files", []):
        if f.get("name") == file_name:
            return {"folder": folder, "file": f}, None
    return None, {"status": "error", "message": f"Nie znaleziono pliku '{file_name}' w folderze '{folder_name}'"}

# ---------------------------------------
# APLIKACJA FLASK – JEDEN ENDPOINT /agent
# ---------------------------------------

app = Flask(__name__)

@app.route("/agent", methods=["POST"])
def agent_endpoint():
    data = request.get_json(force=True) or {}
    intent = data.get("intent")

    # -----------------------------
    # INTENT: create_folder
    # -----------------------------
    if intent == "create_folder":
        folder_name = data.get("folder")
        if not folder_name:
            return jsonify({"status": "error", "message": "Brak pola 'folder'"}), 400
        result = memory_create_folder(folder_name)
        return jsonify(result)

    # -----------------------------
    # INTENT: list_folders
    # -----------------------------
    if intent == "list_folders":
        result = memory_list_folders()
        return jsonify(result)

    # -----------------------------
    # INTENT: save_note
    # fields: folder, content, optional file_name
    # -----------------------------
    if intent == "save_note":
        folder_name = data.get("folder")
        content = data.get("content")
        file_name = data.get("file_name", "notatka.txt")

        if not folder_name or content is None:
            return jsonify({"status": "error", "message": "Wymagane pola: 'folder', 'content'"}), 400

        folder, err = find_folder_by_name(folder_name)
        if err:
            return jsonify(err), 400

        result = memory_create_in_folder(folder["id"], file_name, content)
        return jsonify(result)

    # -----------------------------
    # INTENT: list_files
    # fields: folder
    # -----------------------------
    if intent == "list_files":
        folder_name = data.get("folder")
        if not folder_name:
            return jsonify({"status": "error", "message": "Brak pola 'folder'"}), 400
        result = list_files_in_folder_by_name(folder_name)
        return jsonify(result)

    # -----------------------------
    # INTENT: read_file
    # fields: folder, file_name
    # -----------------------------
    if intent == "read_file":
        folder_name = data.get("folder")
        file_name = data.get("file_name")

        if not folder_name or not file_name:
            return jsonify({"status": "error", "message": "Wymagane pola: 'folder', 'file_name'"}), 400

        info, err = find_file_in_folder_by_name(folder_name, file_name)
        if err:
            return jsonify(err), 400

        result = memory_read(info["file"]["id"])
        return jsonify(result)

    # -----------------------------
    # INTENT: update_file
    # fields: folder, file_name, content
    # -----------------------------
    if intent == "update_file":
        folder_name = data.get("folder")
        file_name = data.get("file_name")
        content = data.get("content")

        if not folder_name or not file_name or content is None:
            return jsonify({"status": "error", "message": "Wymagane pola: 'folder', 'file_name', 'content'"}), 400

        info, err = find_file_in_folder_by_name(folder_name, file_name)
        if err:
            return jsonify(err), 400

        result = memory_update(info["file"]["id"], content)
        return jsonify(result)

    # -----------------------------
    # INTENT: delete_file
    # fields: folder, file_name
    # -----------------------------
    if intent == "delete_file":
        folder_name = data.get("folder")
        file_name = data.get("file_name")

        if not folder_name or not file_name:
            return jsonify({"status": "error", "message": "Wymagane pola: 'folder', 'file_name'"}), 400

        info, err = find_file_in_folder_by_name(folder_name, file_name)
        if err:
            return jsonify(err), 400

        result = memory_delete(info["file"]["id"])
        return jsonify(result)

    # -----------------------------
    # INTENT nieznany
    # -----------------------------
    return jsonify({"status": "error", "message": f"Nieznany intent: {intent}"}), 400


if __name__ == "__main__":
    # lokalnie możesz przetestować: python agent.py
    app.run(host="0.0.0.0", port=8000)
