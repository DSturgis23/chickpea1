"""
Property name mappings between SevenRooms and eviivo

Maps SevenRooms venue names to eviivo property short names.
Update the placeholder values with actual eviivo property short names
once they are provided.
"""

# Mapping from SevenRooms venue name -> eviivo property shortname
# Set to None or empty string for venues without eviivo accommodation
EVIIVO_PROPERTY_MAPPINGS = {
    "The Bell & Crown": "TheBellBA121",
    "The Dog & Gun": "DogandGunSP4",
    "The Fleur de Lys": "TheFleurdeLysInnBH21",
    "The Grosvenor Arms": "TheGrosvenorArmsSP3",
    "The Manor House Inn": "TheManorHouseInnBA4",
    "The Pembroke Arms": "PembrokeSP2",
    "The Queen's Head": "TheQueensHeadSP5",
}

# Reverse mapping for looking up SevenRooms name from eviivo property
SEVENROOMS_VENUE_MAPPINGS = {v: k for k, v in EVIIVO_PROPERTY_MAPPINGS.items() if v}


def get_eviivo_property(sevenrooms_venue_name):
    """
    Get the eviivo property shortname for a SevenRooms venue

    Args:
        sevenrooms_venue_name: The venue name from SevenRooms

    Returns:
        eviivo property shortname or None if not mapped
    """
    return EVIIVO_PROPERTY_MAPPINGS.get(sevenrooms_venue_name)


def get_sevenrooms_venue(eviivo_property):
    """
    Get the SevenRooms venue name for an eviivo property

    Args:
        eviivo_property: The property shortname from eviivo

    Returns:
        SevenRooms venue name or None if not mapped
    """
    return SEVENROOMS_VENUE_MAPPINGS.get(eviivo_property)


def get_all_eviivo_properties():
    """
    Get all mapped eviivo properties

    Returns:
        Dict of {venue_name: property_shortname} for all mapped properties
    """
    return {k: v for k, v in EVIIVO_PROPERTY_MAPPINGS.items() if v}
