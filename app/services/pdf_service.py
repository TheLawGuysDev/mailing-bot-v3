import io
import os
import re
from typing import List, Optional

import pdfplumber
from PyPDF2 import PdfReader, PdfWriter

from app.config import (
    FROM_NAME,
    FROM_ADDRESS1,
    FROM_ADDRESS2,
    FROM_CITY,
    FROM_STATE,
    FROM_POSTCODE,
)


class AddressBlock:
    def __init__(
        self,
        name: str,
        address1: str,
        address2: Optional[str],
        address3: Optional[str],
        city: str,
        state: str,
        postcode: str,
        country: str = "US",
        title: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company: Optional[str] = None,
        address_notes: Optional[str] = None,
        page: Optional[int] = None,
    ):
        self.name = name
        self.address1 = address1
        self.address2 = address2
        self.address3 = address3
        self.city = city
        self.state = state
        self.postcode = postcode
        self.country = country
        self.title = title
        self.first_name = first_name
        self.last_name = last_name
        self.company = company
        self.address_notes = address_notes
        self.page = page

    def as_dict(self):
        return {
            "name": self.name,
            "address1": self.address1,
            "address2": self.address2 or "",
            "address3": self.address3 or "",
            "city": self.city,
            "state": self.state,
            "postcode": self.postcode,
            "country": self.country,
            "title": self.title or "",
            "first_name": self.first_name or "",
            "last_name": self.last_name or "",
            "company": self.company or "",
            "address_notes": self.address_notes or "",
            "page": self.page,
        }


def insert_blank_after_first_page(pdf_bytes: bytes) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    if len(reader.pages) == 0:
        return pdf_bytes

    first = reader.pages[0]
    writer.add_page(first)

    width = float(first.mediabox.width)
    height = float(first.mediabox.height)
    writer.add_blank_page(width=width, height=height)

    for i in range(1, len(reader.pages)):
        writer.add_page(reader.pages[i])

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def insert_fu_blank_page(pdf_bytes: bytes) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    n = len(reader.pages)
    if n == 0:
        return pdf_bytes

    for i in range(n):
        page = reader.pages[i]
        writer.add_page(page)

        if i == 0:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            writer.add_blank_page(width=w, height=h)

        if i == 1:
            ref = reader.pages[1] if n > 1 else reader.pages[0]
            w = float(ref.mediabox.width)
            h = float(ref.mediabox.height)
            writer.add_blank_page(width=w, height=h)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def is_fu_mailing_type(mailing_type: str | None) -> bool:
    if not mailing_type:
        return False
    mt = mailing_type.strip().upper()
    return mt.startswith("1FU") or mt.startswith("2FU") or mt.startswith("3FU") or mt.startswith("4FU")


def detect_mailing_type(file_name: Optional[str]) -> str:
    if not file_name:
        return "Unknown"

    name = file_name.lower()
    first_token = re.split(r"[\s_\-]+", name)[0]

    if first_token.startswith("dl"):
        return "DL"
    if first_token.startswith("1fu"):
        return "1FU"
    if first_token.startswith("2fu"):
        return "2FU"
    if first_token.startswith("3fu"):
        return "3FU-NSR"
    if first_token.startswith("4fu"):
        return "4FU-LS"

    return "Other"


def infer_mailing_type(file_name: str | None) -> str | None:
    if not file_name:
        return None

    base = os.path.basename(file_name).upper().strip()

    if base.startswith("DL") or base.startswith("DEMAND"):
        return "DL"

    for prefix in ["1FU", "2FU", "3FU", "4FU"]:
        if base.startswith(prefix):
            return prefix

    return None


def split_name_for_stannp(full_name: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not full_name:
        return None, None, None

    tokens = full_name.replace(",", " ").split()
    if not tokens:
        return None, None, None

    titles = {"mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.", "hon", "hon.", "judge", "atty", "atty."}

    title = None
    first = None
    last = None

    first_tok_clean = tokens[0].lower().rstrip(".")
    start_idx = 0
    if first_tok_clean in titles:
        title = tokens[0]
        start_idx = 1

    if start_idx >= len(tokens):
        return title, None, None

    first = tokens[start_idx]
    if start_idx + 1 < len(tokens):
        last = " ".join(tokens[start_idx + 1 :])

    return title, first, last


def extract_addresses_from_pdf(pdf_bytes: bytes) -> dict:
    addresses: List[AddressBlock] = []

    city_state_zip_regex = re.compile(
        r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)$"
    )

    sender_keywords = [
        "the law guys",
        "law guys",
        "employee rights lawyers",
        "employee rights lawyer",
        "law firm",
    ]

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    def is_sender_address_block(name_line: str, address1_line: str, address2_line: str | None,
                                city: str, state: str, postcode: str) -> bool:
        blob = " ".join([
            _norm(name_line),
            _norm(address1_line),
            _norm(address2_line or ""),
            _norm(city),
            _norm(state),
            _norm(postcode),
        ])

        if any(k in blob for k in sender_keywords):
            return True

        from_blob = " ".join([
            _norm(FROM_NAME),
            _norm(FROM_ADDRESS1),
            _norm(FROM_ADDRESS2),
            _norm(FROM_CITY),
            _norm(FROM_STATE),
            _norm(FROM_POSTCODE),
        ])

        if (
            _norm(FROM_POSTCODE)
            and _norm(FROM_STATE)
            and _norm(FROM_ADDRESS1)
            and _norm(FROM_POSTCODE) in blob
            and _norm(FROM_STATE) in blob
            and _norm(FROM_ADDRESS1) in blob
        ):
            return True

        if from_blob and (_norm(FROM_ADDRESS1) and _norm(FROM_ADDRESS1) in blob):
            return True

        return False

    def is_heading_line(line: str) -> bool:
        text = line.strip().upper()
        if not text:
            return False
        if "ADDRESS" in text and not any(ch.isdigit() for ch in text):
            return True
        return False

    def is_care_of_line(line: str) -> bool:
        return re.match(r"^\s*(c/o|care\s+of)\b", line.strip(), re.IGNORECASE) is not None

    def has_digit(line: str) -> bool:
        return any(ch.isdigit() for ch in line)

    def is_po_box(line: str) -> bool:
        return re.match(
            r"^\s*(p\.?\s*o\.?\s*box)\b",
            line.strip(),
            re.IGNORECASE,
        ) is not None

    def looks_like_street_without_number(line: str) -> bool:
        text = line.strip()
        if not text:
            return False

        if is_heading_line(text):
            return False
        if is_care_of_line(text):
            return False

        street_suffixes = {
            "st", "street",
            "ave", "avenue",
            "rd", "road",
            "dr", "drive",
            "ln", "lane",
            "blvd", "boulevard",
            "ct", "court",
            "cir", "circle",
            "way",
            "pkwy", "parkway",
            "pl", "place",
            "ter", "terrace",
            "trl", "trail",
            "hwy", "highway",
        }

        cleaned = re.sub(r"[^\w\s]", "", text).strip()
        if not cleaned:
            return False

        parts = cleaned.split()
        if not parts:
            return False

        last_word = parts[-1].lower()
        return last_word in street_suffixes

    def parse_page(lines: List[str], page_number: int) -> List[AddressBlock]:
        page_addresses: List[AddressBlock] = []

        for idx, line in enumerate(lines):
            m = city_state_zip_regex.match(line)
            if not m:
                continue

            city = m.group("city").strip()
            state = m.group("state").strip()
            postcode = m.group("zip").strip()
            city_idx = idx

            address1_idx = None
            search_start = max(0, city_idx - 4)

            for j in range(city_idx - 1, search_start - 1, -1):
                if not lines[j].strip():
                    break

                if (
                    has_digit(lines[j])
                    or is_po_box(lines[j])
                    or looks_like_street_without_number(lines[j])
                ):
                    address1_idx = j
                    break

            if address1_idx is None:
                continue

            address1_line = lines[address1_idx].strip()

            name_idx = None
            extra_lines_above_street: List[int] = []

            name_search_start = max(0, address1_idx - 4)
            for j in range(address1_idx - 1, name_search_start - 1, -1):
                text = lines[j].strip()
                if not text:
                    break
                if is_heading_line(text):
                    break
                if is_care_of_line(text):
                    extra_lines_above_street.append(j)
                    continue
                name_idx = j
                break

            if name_idx is None:
                continue

            name_line = lines[name_idx].strip()

            between_indices = list(range(name_idx + 1, address1_idx))
            for j in extra_lines_above_street:
                if j not in between_indices and name_idx < j < address1_idx:
                    between_indices.append(j)
            between_indices = sorted(set(between_indices))

            extra_lines: List[str] = []
            for j in between_indices:
                text = lines[j].strip()
                if text and not is_heading_line(text):
                    extra_lines.append(text)

            company_name: Optional[str] = None
            address_notes: Optional[str] = None
            filtered_extra_lines: List[str] = []

            for text in extra_lines:
                if is_care_of_line(text):
                    address_notes = text
                    m_co = re.search(r"c/o\s+(.+)", text, re.IGNORECASE)
                    if m_co:
                        company_name = m_co.group(1).strip(" ,")
                    else:
                        company_name = re.sub(r"c/o", "", text, flags=re.IGNORECASE).strip(" ,")
                else:
                    filtered_extra_lines.append(text)

            address2_line: Optional[str] = None
            address3_line: Optional[str] = None

            if len(filtered_extra_lines) == 1:
                address2_line = filtered_extra_lines[0]
            elif len(filtered_extra_lines) >= 2:
                address2_line = filtered_extra_lines[0]
                address3_line = ", ".join(filtered_extra_lines[1:])

            title, first_name, last_name = split_name_for_stannp(name_line)

            if is_sender_address_block(
                name_line=name_line,
                address1_line=address1_line,
                address2_line=address2_line,
                city=city,
                state=state,
                postcode=postcode,
            ):
                continue

            page_addresses.append(
                AddressBlock(
                    name=name_line,
                    address1=address1_line,
                    address2=address2_line,
                    address3=address3_line,
                    city=city,
                    state=state,
                    postcode=postcode,
                    country="US",
                    title=title,
                    first_name=first_name,
                    last_name=last_name,
                    company=company_name,
                    address_notes=address_notes,
                    page=page_number,
                )
            )

        return page_addresses

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return {
                "addresses": [],
                "total_pages": 0,
                "address_pages": [],
                "body_page_start": None,
                "body_page_end": None,
                "body_pdf_bytes": None,
            }

        seen_any_address = False
        last_address_page = 0

        for page_index, page in enumerate(pdf.pages):
            page_number = page_index + 1
            page_text = page.extract_text() or ""
            lines = [line.strip() for line in page_text.splitlines()]

            page_addrs = parse_page(lines, page_number)

            if page_addrs:
                seen_any_address = True
                last_address_page = page_number
                addresses.extend(page_addrs)
            else:
                if seen_any_address:
                    break

    if not addresses:
        address_pages: List[int] = []
        body_page_start = None
        body_page_end = None
    else:
        address_pages = list(range(1, last_address_page + 1))
        if last_address_page < total_pages:
            body_page_start = last_address_page + 1
            body_page_end = total_pages
        else:
            body_page_start = None
            body_page_end = None

    body_pdf_bytes: Optional[bytes] = None

    if body_page_start is not None and body_page_start <= total_pages:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        for i in range(body_page_start - 1, body_page_end):
            writer.add_page(reader.pages[i])

        buf = io.BytesIO()
        writer.write(buf)
        body_pdf_bytes = buf.getvalue()

    return {
        "addresses": addresses,
        "total_pages": total_pages,
        "address_pages": address_pages,
        "body_page_start": body_page_start,
        "body_page_end": body_page_end,
        "body_pdf_bytes": body_pdf_bytes,
    }


def count_pdf_pages(pdf_bytes: bytes) -> int:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)