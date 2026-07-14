"""BIN-based card generator using real BIN database from /root/ceker/bins.csv."""
import random
import csv
from pathlib import Path
from typing import Optional

BIN_CSV = Path("/root/ceker/bins.csv")

# Cache loaded bins
_bin_cache = {}


def _load_bins(brand: str = "visa", card_type: str = "credit", country: str = "US") -> list[dict]:
    """Load BINs from CSV, filtered by brand/type/country."""
    cache_key = f"{brand}_{card_type}_{country}"
    if cache_key in _bin_cache:
        return _bin_cache[cache_key]
    
    results = []
    with open(BIN_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("brand", "").upper() == brand.upper() and
                row.get("type", "").lower() == card_type.lower() and
                row.get("country_code", "").upper() == country.upper()):
                results.append(row)
    
    _bin_cache[cache_key] = results
    return results


def luhn_checksum(card_number: str) -> int:
    digits = [int(d) for d in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10


def luhn_check_digit(partial: str) -> str:
    for d in range(10):
        if luhn_checksum(partial + str(d)) == 0:
            return str(d)
    return "0"


def generate_card(brand: str = "visa", bin_prefix: Optional[str] = None) -> dict:
    """Generate a Luhn-valid card from real BIN database."""
    bins = _load_bins(brand)
    if not bins:
        # Fallback
        bins = [{"bin": "400000", "number_length": "16"}]
    
    # Pick a random BIN or use specified one
    if bin_prefix:
        matching = [b for b in bins if b["bin"].startswith(bin_prefix[:6])]
        bin_info = matching[0] if matching else random.choice(bins)
    else:
        bin_info = random.choice(bins)
    
    prefix = bin_info["bin"]
    card_len = int(bin_info.get("number_length", 16))
    bank_name = bin_info.get("bank_name", "")
    category = bin_info.get("category", "")
    
    # Generate middle digits
    middle_len = card_len - len(prefix) - 1
    middle = "".join(str(random.randint(0, 9)) for _ in range(middle_len))
    
    # Luhn check digit
    partial = prefix + middle
    check = luhn_check_digit(partial)
    card_number = partial + check
    
    # Expiry
    exp_month = random.randint(1, 12)
    exp_year = (2026 + random.randint(1, 4)) % 100
    
    # CVV
    cvv_len = 4 if brand.upper() == "AMEX" else 3
    cvv = "".join(str(random.randint(0, 9)) for _ in range(cvv_len))
    
    return {
        "number": card_number,
        "formatted": " ".join(card_number[i:i+4] for i in range(0, len(card_number), 4)),
        "brand": brand.lower(),
        "bin": prefix,
        "bank": bank_name,
        "category": category,
        "exp_month": f"{exp_month:02d}",
        "exp_year": f"{exp_year:02d}",
        "expiry": f"{exp_month:02d}/{exp_year:02d}",
        "cvv": cvv,
        "luhn_valid": luhn_checksum(card_number) == 0,
    }


def generate_us_address() -> dict:
    streets = [
        "Main Street", "Oak Avenue", "Pine Street", "Maple Avenue",
        "Cedar Boulevard", "Elm Street", "Washington Avenue", "Park Street",
        "Lake Drive", "Hill Road", "River Road", "Forest Avenue",
        "Sunset Boulevard", "Broadway", "Market Street", "Mission Street",
    ]
    cities = [
        ("New York", "NY", "10001"), ("Los Angeles", "CA", "90001"),
        ("Chicago", "IL", "60601"), ("Houston", "TX", "77001"),
        ("Phoenix", "AZ", "85001"), ("San Diego", "CA", "92101"),
        ("Dallas", "TX", "75201"), ("San Jose", "CA", "95101"),
        ("Austin", "TX", "78701"), ("San Francisco", "CA", "94101"),
        ("Seattle", "WA", "98101"), ("Denver", "CO", "80201"),
    ]
    city, state, zip_base = random.choice(cities)
    zip_code = str(int(zip_base) + random.randint(0, 50))
    return {
        "street": f"{random.randint(100, 9999)} {random.choice(streets)}",
        "city": city, "state": state, "zip": zip_code, "country": "US",
    }


if __name__ == "__main__":
    for brand in ["visa", "mastercard"]:
        card = generate_card(brand)
        print(f"\n{brand.upper()} [{card['bank']}]:")
        print(f"  Number: {card['formatted']}")
        print(f"  BIN: {card['bin']} ({card['category']})")
        print(f"  Expiry: {card['expiry']}  CVV: {card['cvv']}")
        print(f"  Luhn: {card['luhn_valid']}")
    
    addr = generate_us_address()
    print(f"\nAddress: {addr['street']}, {addr['city']}, {addr['state']} {addr['zip']}")
    
    # Stats
    visa_bins = _load_bins("visa")
    mc_bins = _load_bins("mastercard")
    print(f"\nBIN DB: {len(visa_bins)} Visa, {len(mc_bins)} Mastercard")
