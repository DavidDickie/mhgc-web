"""Names computer empires give the systems they settle or capture (Dave 2026-11-13: "Have the bots
name systems"; DECISIONS W-14).

One list per default race name (constants.DEFAULT_RACE_NAMES), themed on the race, and one pool
per bot personality for races with any other name.  Every name is one token of letters, digits
and _, at most NAME_MAX (12) characters, and every name is unique across all the lists, so two
computer empires never reach for the same name.  When a race runs out, `npr/naming.py` adds
_II, _III ... variants, then numbered names.
"""
from __future__ import annotations

RACE_NAMES: dict[str, tuple[str, ...]] = {
    "Porkines": (
        "Hamburgia", "Sty_Prime", "Truffleton", "Baconia", "Snoutholm", "Hogsworth",
        "Porkopolis", "Mudwallow", "Oinkara", "Sowbelly", "Crackling", "Ham_Haven",
        "Trotterdam", "Swillmoor", "Grunting_Bay", "Chopsville", "Piglet_Rock", "Lardvale",
        "Boarzilla", "Curlytail"),
    "Groachi": (
        "Scuttleton", "Grumblehive", "Carapax", "Chitinia", "Sewerholm", "Crumbworld",
        "Grouchland", "Moultmire", "Leggy_Six", "Nightscurry", "Crevice", "Grimeholt",
        "Roachford", "Scurrydown", "Unsquished", "Skitterpit", "Drainmoor", "Grimecrawl",
        "Baseboard", "Grumpshire"),
    "Barnacle_Boys": (
        "Hullhugger", "Saltcrust", "Clingport", "Tidepool", "Brine_Bight", "Shipbottom",
        "Kelpstead", "Limpet_Lane", "Scuttlebutt", "Bilgewater", "Driftwood", "Gooseneck",
        "Anchorage", "Low_Tide", "Crustaceana", "Seaspray", "Stickfast", "Wharfside",
        "Dock_Rot", "Keelhaul"),
    "Grunts": (
        "Fort_Sarge", "Boot_Camp", "Drill_Field", "Mess_Hall", "Foxhole", "Latrine_Dig",
        "Parade_Rock", "Bunkerton", "Trenchmouth", "KP_Duty", "Hup_Two", "Barracks",
        "Sandbag", "Reveille", "Chow_Line", "Ten_Hut", "Front_Line", "Dogtag", "Muster",
        "Bivouac"),
    "Freepeople": (
        "Groovania", "Peace_Out", "Daisy_Chain", "Love_Bead", "Far_Out", "Mellowmoor",
        "Tie_Dye", "Free_Lunch", "Kumbaya", "Wavelength", "Sunbeam", "Harmonia", "Good_Vibes",
        "Hemp_Hollow", "Commune_One", "Patchouli", "Barefoot", "Driftaway", "Flowerpot",
        "No_Rules"),
    "Haldermen": (
        "Halderhall", "Old_Halder", "Stuffington", "Monocle_Hill", "Tweedsbury", "Wigmore",
        "Sherry_Hill", "Ledgerton", "Haldermoor", "Portly_Manor", "Snifter", "Brassbutton",
        "Ascot", "Starchcollar", "Pemberton", "Upper_Crust", "Haldergate", "Tophat_Rise",
        "Harrumph", "Gout_Springs"),
    "Boviners": (
        "Moo_Lagoon", "Cud_Valley", "Udderly", "Bovinia", "Holstein", "Pasture_Ho", "Milkway",
        "Steerforth", "Cowabunga", "Grazewood", "Herdholme", "Bullseye", "Haybale",
        "Clover_Patch", "Cowlick", "Butterhorn", "Beefeater", "Lowing_Lea", "Moonbarn",
        "Stampede"),
    "Badhombres": (
        "Dustbowl", "Tombstone", "Gulch", "Rio_Malo", "Sombrero", "Six_Gun", "Deadwood",
        "Hangtree", "Rattlesnake", "Tumbleweed", "Bandito_Bay", "Spur_Town", "Outlaw_Mesa",
        "Loco_Hill", "Cactus_Jack", "Pistolero", "Bad_Water", "Vamoose", "Desperado",
        "Hoosegow"),
    "Ravaging_Bugs": (
        "Swarmhome", "Devourax", "Chompworld", "Larva_Pit", "Hive_Nine", "Munchmire",
        "Stinger", "Mandible", "Skitterhive", "Gnawhold", "Egg_Sac", "Buzzkill", "Ravenous",
        "Locustia", "Antlion", "Cocoon", "Nest_Prime", "Bitemark", "Molt_Moon", "Infestia"),
    "Hopeless": (
        "Why_Bother", "Gloomhaven", "Meh", "Despairia", "Lost_Cause", "Dreary", "Futility",
        "Rainy_Day", "Sigh", "Downcast", "Last_Straw", "Dismal", "Not_Again", "Bleakwater",
        "Oh_Well", "Doomsday", "Glumshire", "Woebegone", "Long_Face", "Low_Hopes"),
    "Blutos": (
        "Brutopia", "Knuckles", "Thumpton", "Bicepia", "Big_Lug", "Smashville", "Headlock",
        "Beardmoor", "Brawler", "Bruiser", "Meathook", "Bully_Rock", "Flex_Point", "Haymaker",
        "Punchbowl", "Clobber", "Tough_Nut", "Swole", "Ironjaw", "Sockeroo"),
    "Mangos": (
        "Mango_Tango", "Pulpville", "Juicy_Rock", "Tropica", "Pit_Stop", "Ripeland",
        "Nectaria", "Sweetwater", "Fruitopia", "Peelhaven", "Mangrove", "Stickyhand",
        "Smoothie", "Orchard", "Golden_Pulp", "Chutney", "Sunripe", "Kernel", "Dried_Mango",
        "Lassi"),
    "Gollywogs": (
        "Gollyhill", "Goshwood", "Gee_Whiz", "Wobbleton", "Fiddlesticks", "Jeepers",
        "Hullabaloo", "Gadzooks", "Golly_Gosh", "Whoopsie", "Kerfuffle", "Topsy_Turvy",
        "Gobsmack", "Doodah", "Hootenanny", "Flibbert", "Wigglewood", "Bamboozle",
        "Thingamajig", "Whatsit"),
    "Bratwursts": (
        "Wurstburg", "Sauerkraut", "Mustard_Hill", "Bierhalle", "Pretzelheim", "Sizzleton",
        "Grillplatz", "Linkstadt", "Kielbasa", "Oompah", "Lederhosen", "Bunsville",
        "Frankfurter", "Bockwurst", "Knackwurst", "Schnitzel", "Stein_Stadt", "Brauhaus",
        "Casingdorf", "Bratapolis"),
    "Googly_eyes": (
        "Eyesore", "Peepers", "Blinkton", "Staring_Sea", "Lookout", "Pupilia", "Wink_Rock",
        "Gawk_Hollow", "Squintwood", "Ogleworth", "Eyeball", "Lash_Point", "Gogglemoor",
        "Retina", "Iris_Prime", "Ocularia", "Stare_Down", "Peekaboo", "Cyclopia", "Bug_Eye"),
    "Ratfinks": (
        "Snitchville", "Cheesemoor", "Tattletale", "Squealer", "Nibble_Nook", "Gnawburg",
        "Whisker_Gap", "Rodentia", "Turncoat", "Weaselton", "Cheddarholm", "Fink_Hole",
        "Double_Cross", "Squeakton", "Stoolpigeon", "Ratchet", "Tailspin", "Crumb_Snatch",
        "Burrow", "Rat_Race"),
    # the races added for the 20- and 25-empire maps (G-30)
    "Snorklers": (
        "Snorkelton", "Deep_Breath", "Bubbleport", "Flipper_Bay", "Goggle_Reef", "Lagoonia",
        "Air_Hose", "Coralholm", "Wetsuit", "Plunge_Pool", "Fathomere", "Gurgle_Gulf",
        "Mask_Rock", "Splashdown", "Divers_Rest", "Tide_Tunnel", "Seaweed_Sea", "Blowhole",
        "Bends_Bay", "Shallows"),
    "Wombatians": (
        "Wombatia", "Burrowmere", "Cube_Hollow", "Dirtnap", "Pouchton", "Diggers_Den",
        "Grassmunch", "Stumpy_Leg", "Snugburrow", "Outback", "Bushland", "Wallowby",
        "Dust_Bowl", "Tunnelwick", "Sleepy_Hill", "Rootcellar", "Furrowfield", "Nightgrub",
        "Wombat_Gap", "Mound_Prime"),
    "Glorpers": (
        "Glorpia", "Oozeville", "Sludge_Pit", "Gloopmire", "Slurpton", "Jellymoor",
        "Splorch", "Drool_Basin", "Blorp_Prime", "Squelch", "Gunkfield", "Slimeholm",
        "Goober_Bay", "Gelatinia", "Puddleton", "Muckluck", "Viscosa", "Wobble_Rock",
        "Glorp_Major", "Mucilage"),
    "Fuzzballs": (
        "Fluffhaven", "Lintworld", "Purrsville", "Fuzzopolis", "Static_Fur", "Furball_Bay",
        "Pom_Pom", "Cuddle_Cove", "Shedmoor", "Hairball", "Softpaw", "Furrytown",
        "Dander_Dell", "Plushia", "Snugglebury", "Down_Feather", "Velveteen", "Moppet",
        "Dustbunny", "Fuzz_Major"),
    "Mudskippers": (
        "Mudflat", "Skipton", "Brackish", "Silt_Hollow", "Estuaria", "Mudhole",
        "Gill_Gap", "Hopalong", "Ooze_Bank", "Low_Water", "Bogside", "Marshmere",
        "Fin_Walker", "Reedbed", "Slither_Bay", "Wetland", "Puddle_Jump", "Sloshport",
        "Tideflat", "Mire_Prime"),
    "Blobsters": (
        "Blobton", "Globule", "Amorphia", "Lumpville", "Shapeless", "Bulge_Bay", "Engulf",
        "Absorbia", "Dollop", "Big_Blob", "Splat_City", "Jigglemoor", "Gobbet", "Plop_Point",
        "Blobfield", "Morphmoor", "Squidge", "Gooberton", "Ooze_Prime", "Lumpen"),
    "Noodlers": (
        "Spaghettia", "Ramen_Rock", "Linguine", "Udonia", "Al_Dente", "Fettuccine",
        "Slurp_City", "Noodle_Nook", "Macaroni", "Penne_Point", "Lasagna", "Broth_Bay",
        "Soba_Sound", "Vermicelli", "Ravioli", "Rigatoni", "Orzo_Major", "Chopstick",
        "Tagliatelle", "Gnocchi"),
    "Space_Hamsters": (
        "Wheelworld", "Cheek_Pouch", "Seedstash", "Hamsterdam", "Squeakwheel", "Sawdust",
        "Water_Drip", "Nibblesby", "Gerbilton", "Tubeway", "Cage_Prime", "Sunflower",
        "Fluffcheek", "Runaround", "Pellet_Pile", "Treadmill", "Burrowbox", "Whiskerby",
        "Hamhock", "Nestbed"),
    "Cogwheels": (
        "Gearhaven", "Sprocket", "Clockwork", "Ratchetton", "Flywheel", "Cam_Shaft",
        "Spindle", "Gearbox", "Pistonia", "Torque_Town", "Axle_Point", "Lubrication",
        "Cotter_Pin", "Escapement", "Bolt_Bay", "Mainspring", "Grindstone", "Tick_Tock",
        "Rivetton", "Pinion"),
}

# For computer empires with any other race name, by personality.  A bot takes every 25th name
# (MAX_EMPIRES) from its personality's pool of 50, offset by its empire id, so no two bots share a
# name, at every game size up to 25 empires (G-30; was every 16th of 32).
PERSONA_NAMES: dict[str, tuple[str, ...]] = {
    "aggressive": (
        "Doomspire", "Skullcrag", "Ironfist", "Warmonger", "Blitzhold", "Bonecrusher",
        "Ravager", "Gutpunch", "Spikemoor", "Grimhold", "Blood_Moon", "Wreckage", "Havoc",
        "Carnage", "Smashmouth", "Nailbiter", "Battlecry", "Fury_Road", "Sledge", "Warpath",
        "Killjoy", "Rampart", "Gauntlet", "Crushpoint", "Thunderdome", "Mayhem", "Bombast",
        "Scorchmark", "Rubblehead", "Ironclad", "Shrapnel", "Bludgeon",
        "Warhammer", "Bayonet", "Siegeworks", "Bloodfang", "Brimstone", "Torment", "Ravenrock",
        "Deathgrip", "Firestorm", "Gorehold", "Bulwark", "Battleaxe", "Scourge", "Vengeance",
        "Hellmouth", "Steelfang", "Onslaught", "Pillage"),
    "builder": (
        "Tidy_Acres", "Smugsworth", "Fine_Estate", "Neatfield", "Lawnmore", "Pavedvale",
        "Prim_Point", "Brickhaven", "Tidyville", "Polished", "Blueprint", "Masonry",
        "Cornerstone", "Quaintly", "Picket_Fence", "Spotless", "Upkeep", "Well_Kept",
        "Prosperia", "Gleamwood", "Our_Best_One", "Showcase", "Deluxe", "Model_Town",
        "Orderly", "Trimhedge", "Starched", "Exquisite", "Laurels", "Grand_Plan", "Mortarboard",
        "Superior",
        "Gardenia", "Manicured", "Fine_China", "Heritage", "Bellwether", "Craftsman",
        "Silverware", "Grandview", "Proud_Acres", "Tasteful", "Pinnacle", "Highbrow",
        "Topiary", "Gold_Leaf", "Elegance", "Freshpaint", "Landmark", "Well_Built"),
    "opportunist": (
        "Finders_Keep", "Loophole", "Sly_Corner", "Backroom", "Fine_Print", "Swindle",
        "Shadyside", "Sidedeal", "Knockoff", "Fence_Post", "Grifton", "Bargain_Bin",
        "Smokescreen", "Pickpocket", "Cunningham", "Foxden", "Rugpull", "Wink_Wink", "Sleight",
        "Slipaway", "Quick_Buck", "Hustleburg", "Underhand", "Shellgame", "Racketeer",
        "Sneakaway", "Lucky_Find", "Dodgeton", "Moonlighter", "Haggle", "Fast_One",
        "Sticky_Deal",
        "Snake_Oil", "Black_Market", "Pawnshop", "Hot_Goods", "Sly_Fox", "Cardsharp",
        "Bait_Switch", "Short_Change", "Back_Alley", "Con_Artist", "Grabbag", "Slick_Deal",
        "Fly_By_Night", "Easy_Money", "Side_Door", "Skim_Top", "Two_Faced", "Hoodwink"),
}

ROMAN = ("II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

__all__ = ["RACE_NAMES", "PERSONA_NAMES", "ROMAN"]
