"""
Etsy / Shop Uploader allowed values for _underscore attribute columns.

Sourced from: Y2KASEshop.xlsx → allowed_values sheet (authoritative Etsy taxonomy).
These are CaSE-SenSiTivE — must match exactly.

Update this file whenever Etsy adds or renames values (re-export a template from
Shop Uploader and run: python scripts/dump_allowed_values.py).
"""

import re

# Category must be in Shop Uploader format: "Name (numeric_id)"
# e.g. "Phone Cases (873)"  — NOT a breadcrumb like "Electronics > Accessories > ..."
CATEGORY_RE = re.compile(r'^.+\s+\(\d+\)$')

COLORS: frozenset[str] = frozenset([
    "Beige", "Black", "Blue", "Bronze", "Brown", "Clear", "Copper",
    "Gold", "Gray", "Green", "Orange", "Pink", "Purple", "Rainbow",
    "Red", "Rose gold", "Silver", "White", "Yellow",
])

OCCASIONS: frozenset[str] = frozenset([
    "1st birthday", "Anniversary", "Baby shower", "Bachelor party",
    "Bachelorette party", "Back to school", "Baptism", "Bar & Bat Mitzvah",
    "Birthday", "Bridal shower", "Confirmation", "Divorce & breakup",
    "Engagement", "First Communion", "Graduation", "Grief & mourning",
    "Housewarming", "LGBTQ pride", "Moving", "Pet loss", "Prom",
    "Quinceañera & Sweet 16", "Retirement", "Wedding",
])

HOLIDAYS: frozenset[str] = frozenset([
    "April Fools'", "Christmas", "Cinco de Mayo", "Easter",
    "Father's Day", "Halloween", "Hanukkah", "Independence Day",
    "Kwanzaa", "Lunar New Year", "Mother's Day", "New Year's",
    "Passover", "St Patrick's Day", "Thanksgiving", "Valentine's Day",
    "Veterans Day",
])

# Full Etsy _material_multi allowed list (400+ entries, exact casing required).
MATERIALS: frozenset[str] = frozenset([
    "Abacá", "Abalone shell", "ABS", "Acacia", "Acrylic", "Actinolite",
    "African padauk", "Agate", "Alabaster", "Alder", "Alexandrite",
    "Alligator leather", "Almandine", "Alpaca", "Aluminum", "Amazonite",
    "Amber", "Amethyst", "Ametrine", "Ammolite", "Andalusite", "Angelite",
    "Angora", "Antler", "Apatite", "Apophyllite", "Aqua aura", "Aquamarine",
    "Aragonite", "Archival paper", "Argentium sterling silver",
    "Artificial silk", "Ash", "Aspen", "Aventurine", "Azurite", "Bagasse",
    "Ball clay", "Balsa", "Bamboo", "Banded agate", "Barkcloth",
    "Barn wood", "Basalt", "Basswood", "Batiste", "Batting", "Beech",
    "Beeswax", "Biotite", "Birch", "Bison leather", "Blackwood",
    "Bloodstone", "Blotting paper", "Blueprint paper", "Bone & horn",
    "Bone china", "Bookboard", "Bouclé", "Boxwood", "Brass", "Brick",
    "Britannia silver", "Broadcloth", "Brocade", "Bronze", "Buckeye",
    "Buckram", "Burlap", "Butternut", "Cable knit", "Calcite",
    "Calf leather", "Cambric", "Camel hair", "Camphor", "Canvas",
    "Carbon steel", "Cardboard", "Cardstock", "Carnelian", "Cashmere",
    "Cast aluminum", "Cast iron", "Cat hair", "Catalpa", "Catgut",
    "Cedar", "Celestite", "Cellophane", "Celluloid", "Cement", "Ceramic",
    "Chalcedony", "Challis", "Chambray", "Chanderi", "Charmeuse",
    "Charoite", "Cheesecloth", "Chenille", "Cherry", "Chestnut",
    "Chiengora", "Chiffon", "Chino", "Chintz", "Chrome", "Chrysoberyl",
    "Chrysocolla", "Chrysoprase", "Citrine", "Clam shell", "Clay", "Coal",
    "Cocobolo", "Coconut", "Coir", "Collage sheets", "Composite", "Conch",
    "Concrete", "Construction paper", "Copper", "Coral", "Corduroy",
    "Cork", "Corkwood", "Cotton", "Cottonwood", "Cowhide", "Cowrie shell",
    "Crazy lace agate", "Crepe", "Crepe back satin", "Crepe de chine",
    "Crepe paper", "Crinoline", "Crystal", "Cubic zirconia", "Cumaru",
    "Cuprite", "Cupronickel", "Cypress", "Damascus steel", "Damask",
    "Danburite", "Decorative paper", "Decoupage paper", "Deer leather",
    "Demantoid", "Dendritic agate", "Denim", "Desert rose",
    "Developing paper", "Diamond", "Diopside", "Dioptase", "Dobby",
    "Dogwood", "Dola silk", "Double face", "Double knit", "Down",
    "Drawing paper", "Dried flowers", "Driftwood", "Dumortierite",
    "Duplicating paper", "Earthenware", "Ebony", "Elm", "Emerald",
    "Enamel", "Epidote", "Eucalyptus", "Eyelet", "Fabric", "Faille",
    "Faux fur", "Faux leather", "Faux pearls", "Feather", "Felt",
    "Fiberglass", "Fique", "Fir", "Fire agate", "Flannel", "Flax",
    "Fleece", "Flint", "Flower agate", "Fluorite", "Foam", "Foil",
    "Fossil", "Fur", "Gabardine", "Garnet", "Gauze", "Gazar", "Gemstone",
    "Geode", "Georgette", "German silver", "Gingham", "Glass",
    "Goat leather", "Gold", "Gold filled", "Golden beryl", "Grains",
    "Grandidierite", "Granite", "Grass", "Grasscloth", "Guanaco",
    "Gum wood", "Gunmetal", "Hackberry", "Handmade paper", "Heliodor",
    "Hematite", "Hemlock", "Hemp", "Herringbone", "Hessonite", "Hickory",
    "Hiddenite", "Hornbeam", "Horse hair", "Horse leather", "Houndstooth",
    "Howlite", "Human hair", "Idocrase", "Interlock knit", "Iolite",
    "Ipe", "Iroko", "Iron", "Ironstone", "Ironwood", "Jacquard", "Jade",
    "Jadeite", "Jasper", "Jatoba", "Jersey knit", "Jet", "Jute",
    "Kaolin clay", "Kenaf", "Kente", "Kevlar", "Khadi", "Kingwood",
    "Kornerupine", "Kraft paper", "Kunzite", "Kyanite", "Labradorite",
    "Lace", "Lace paper", "Lacewood", "Lambswool", "Lame & metallic",
    "Lanolin", "Lapis lazuli", "Larch", "Larimar", "Latex", "Lava",
    "Lead", "Leather", "Lepidolite", "Limba", "Limestone", "Limpet shell",
    "Linen", "Linoleum", "Lithographic paper", "Llama", "Locust",
    "Lucite", "Lurex", "Lyocell", "Madras", "Magazine paper", "Magnesium",
    "Mahogany", "Malachite", "Maple", "Marble", "Marblewood", "Marcasite",
    "Matelassé", "Maw sit sit", "Merino", "Mesh", "Metal", "Meteorite",
    "Microbeads", "Microfiber", "Minky", "Mirror", "Mitre shell",
    "Modacrylic", "Modal", "Mohair", "Moiré", "Moissanite", "Moldavite",
    "Moleskin", "Moon snail shell", "Moonstone", "Morganite", "Morion",
    "Moss", "Moss agate", "Mother of pearl", "Muga silk", "Mulberry paper",
    "Muslin", "Mylar", "Mysore silk", "Nassa shell", "Natural fiber",
    "Nautilus shell", "Neoprene", "Nephrite", "Netting", "Newsprint",
    "Nickel", "Niobium", "Nordic gold", "Nylon", "Oak", "Obsidian",
    "Oilcloth", "Olefin", "Olive shell", "Olive wood", "Onyx", "Opal",
    "Operculum shell", "Organdy", "Organza", "Origami paper", "Orthoclase",
    "Ostrich leather", "Palladium", "Pallet wood", "Palm", "Paper",
    "Paraffin", "Parchment paper", "Pashmina", "PCA", "Pearl", "Percale",
    "Peridot", "Petrified wood", "Pewter", "Photo & imaging paper",
    "Pietersite", "Pig leather", "Pine", "Pink ivory", "Pique", "Piña",
    "PLA", "Plaster", "Plastic", "Platinum", "Plume agate", "Plywood",
    "PMMA", "Polyamide", "Polyester", "Polymer clay", "Polypropylene",
    "Pongee", "Ponté knit", "Poplar", "Poplin", "Porcelain", "Possum",
    "Poster board", "Prasiolite", "Prehnite", "Printer paper", "Purl",
    "Purpleheart", "PVA", "PVC", "Pyrite", "Qiviut", "Quartz",
    "Quartzite", "Rabbit", "Raffia", "Ramie", "Raschel", "Rattan",
    "Rayon", "Reclaimed wood", "Redheart", "Resin", "Rhodochrosite",
    "Rhodolite", "Rhodonite", "Rhyolite", "Rib knit", "Rice paper",
    "Ripstop", "Riverstone", "Rock crystal", "Rose gold", "Rose quartz",
    "Rosewood", "Rubber", "Ruby", "Ruby zoisite", "Sal", "Sand",
    "Sandalwood", "Sandstone", "Sapphire", "Sardonyx", "Sari silk",
    "Sassafras", "Sateen", "Satin", "Scallop shell", "Scapolite",
    "Scolecite", "Scrim", "Seagrass", "Seeds", "Seersucker", "Selenite",
    "Sequins", "Seraphinite", "Serpentine", "Shantung & dupioni",
    "Sheep leather", "Sheepskin", "Shell", "Sherpa", "Shungite",
    "Silicone", "Silk", "Sillimanite", "Silver", "Silver filled", "Sinew",
    "Sisal", "Sketching paper", "Slate", "Snake leather", "Soapstone",
    "Sodalite", "Solder", "Soy", "Spandex", "Spectrolite", "Sphene",
    "Spindle shell", "Spinel", "Sponge", "Spruce", "Stainless steel",
    "Steel", "Sterling silver", "Stone", "Stoneware", "Straw", "Styrene",
    "Suede", "Sugi", "Sugilite", "Sunstone", "Super seven",
    "Surgical steel", "Suri", "Sweetgum", "Synthetic fiber", "Taffeta",
    "Tanzanite", "Teak", "Tektite", "Tencel", "Terry cloth",
    "Thermal knit", "Thunderegg", "Tibetan silver", "Tiger's eye", "Tin",
    "Tissue paper", "Titanium", "Topaz", "Tourmaline", "Tracing paper",
    "Transfer paper", "Travertine", "Triacetate", "Tricot",
    "Triton shell", "Tulle", "Tungsten", "Tupelo", "Turbo shell",
    "Turquoise", "Tussar silk", "Tweed", "Twill", "Ultrasuede",
    "Unakite", "Variscite", "Vellum", "Velour", "Velvet", "Velveteen",
    "Vicuña", "Vinyl", "Viscose", "Voile", "Volute shell", "Walnut",
    "Washi paper", "Wax", "Wax paper", "Wenge", "White gold", "Wicker",
    "Willow", "Wood", "Wool", "Wrapping paper", "Writing paper",
    "Wrought aluminum", "Wrought iron", "Yak", "Yellow gold", "Zeolite",
    "Zinc", "Zircon", "Zirconium",
])


def closest_match(value: str, allowed: frozenset[str], n: int = 3) -> list[str]:
    """Return up to n allowed values whose lowercase form contains or matches value."""
    v = value.lower()
    return [a for a in sorted(allowed) if v in a.lower() or a.lower() in v][:n]
