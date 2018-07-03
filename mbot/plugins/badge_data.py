'''
This file is used to store all information required for the `Badges` plugin.
It consists of two dictionaries;

BADGE_DATA {
    <badge_id>: {                  # Unique identifier for the badge. Should match what is shown on the badge itself.
        "badge_name": ...,         # The human reaedable name for the badge. Usually the name of the game series.
        "craftable": ...,          # Indicates if the badge is craftable; if true, the crafting costs must be specified.
        "has_foil": ...,           # Indicates if the badge has a foil version
        "games": [],               # List of all games that this badge covers.
        "standard_cost": {         # Crafting cost for the standard version of the badge; must be present if
            "fragments": ...,      # the badge is marked as `craftable`.
            "foil_fragments": ...
        },
        "foil_cost": {             # Crafting cost for the foil version of the badge; must be present if both
            "foil_fragments": ...  # `craftable` and `has_foil` are set to `True`.
        }
    }
}

BADGE_DATA stores data on all badges


BADGE_MAP {
    "name of game as seen in the discord client": <badge_id>
}

BADGE_MAP maps all game names as seen in the discord desktop client to their respective badge ID
          this is more of a convenience data store so we don't have to iterate the BADGE_DATA dict


Fragments are earned at a rate of 1 per minute, rounded down.
There is a 1% chance that a fragment is foil.
'''


BADGE_DATA = {
    '00': {
        'badge_name': 'Witcher',
        'craftable': True,
        'has_foil': True,
        'games': ['The Witcher', 'The Witcher 2', 'The Witcher 3'],
        'standard_cost': {
            'fragments': 1000,
            'foil_fragments': 0
        },
        'foil_cost': {
            'fragments': 2000,
            'foil_fragments': 100
        }
    },

    '01': {
        'badge_name': 'Marko',
        'craftable': True,
        'has_foil': True,
        'games': [],
        'standard_cost': {
            'fragments': 5000,
            'foil_fragments': 0
        },
        'foil_cost': {
            'fragments': 10000,
            'foil_fragments': 500
        }
    }
}


BADGE_MAP = {
    'The Witcher 3: Wild Hunt': '00',
    'The Witcher 3': '00',
    'The Witcher 2': '00',
    'The Witcher 2: Enhanced Edition': '00',
    'The Witcher': '00',
    'The Witcher: Enhanced Edition': '00',

    'markobot.xyz': '01'
}
