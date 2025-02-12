import json

class SettingsFileManagement:
    def update_entry(self, main_key: str, new_data):
        """Update the settings file with new data."""
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return
            # find the main key in file
        if data[main_key]:
            data[main_key].update(new_data)

        with open('settings.json', 'w') as f:
            json.dump(data, f, indent=4)

    def remove_entry(self, main_key: str, key: str):
        """Remove the entry from the settings file."""
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return

        if data[main_key]:
            data[main_key].pop(key, None)

        with open('settings.json', 'w') as f:
            json.dump(data, f, indent=4)

    def get_entry(self, main_key: str):
        """Retrieve the entry from the settings file."""
        try:
            with open('settings.json', 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('Erreur : Le fichier settings.json n\'a pas été trouvé.')
            return

        return data[main_key]

settings_file_management = SettingsFileManagement()
