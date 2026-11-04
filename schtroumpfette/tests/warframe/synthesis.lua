-- Extrait de https://wiki.warframe.com/w/Module:Synthesis/data (CC BY-NC-SA 3.0)
local synthesisData = {
	["Lancer"] = {
		_IgnoreEntry = false,
		Locations = { "Cambria", "Caloris", "Pantheon", "Elion", "Cassini", "Kappa" },
		IsImprint = true,
		Size = "Small",
		ScanPoints = 4,
		Standing = 2513,
	},
	["Corrupted Lancer"] = {
		_IgnoreEntry = false,
		Locations = { "Hepit", "Ukko" },
		IsImprint = false,
		Size = "Small",
		ScanPoints = 4,
		Standing = 2513,
	},
	["Shield Lancer"] = {
		_IgnoreEntry = false,
		Locations = { "Pantheon", "Caloris", "Elion", "Cassini" },
		IsImprint = false,
		Size = "Small",
		ScanPoints = 4,
		Standing = 2513,
	},
	["Hellion"] = {
		_IgnoreEntry = false,
		Locations = { "Ara", "Lex", "Rusalka" },
		IsImprint = false,
		Size = "Big",
		ScanPoints = 4,
		Standing = 2563,
	},
	["Eviscerator"] = {
		_IgnoreEntry = false,
		Locations = { "Ara", "Lex", "Ker" },
		IsImprint = false,
		Size = "Big",
		ScanPoints = 4,
		Standing = 2538,
	},
	["Arid Eviscerator"] = {
		_IgnoreEntry = false,
		Locations = { "Ara" },
		IsImprint = true,
		Size = "Big", -- unsure
		ScanPoints = 3, -- unsure
		Standing = -1, -- unsure
	},
	["Crewman"] = {
		_IgnoreEntry = false,
		Locations = { "Copernicus" },
		IsImprint = true,
		Size = "Big", -- unsure 
		ScanPoints = 4, -- unsure
		Standing = -1,
	},
}

return synthesisData
