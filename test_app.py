import pytest
import json
import base64
import sys
import os

# Add the api directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api'))

from api.index import app, text_to_number, number_to_text, base64_to_number, number_to_base64

@pytest.fixture
def client():
    """Create a test client for the Flask application"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


# ----------------------------
# Unit tests for pure functions
# ----------------------------

class TestTextToNumber:
    """Test text to number conversion"""

    def test_basic_numbers(self):
        assert text_to_number("one") == 1
        assert text_to_number("ten") == 10

    def test_zero_variants(self):
        assert text_to_number("zero") == 0
        assert text_to_number("nil") == 0

    def test_invalid_values(self):
        with pytest.raises(ValueError):
            text_to_number("")
        with pytest.raises(ValueError):
            text_to_number("foobar")

    def test_punctuation_and_case(self):
        assert text_to_number("One!") == 1
        assert text_to_number("TWO.") == 2

    def test_text_gap_bug_exposing(self):
        """Bug-exposing: should support 'forty two'"""
        assert text_to_number("forty two") == 42


class TestNumberToText:
    def test_small_and_large(self):
        assert number_to_text(1) == "one"
        assert number_to_text(42) == "forty-two"
        assert number_to_text(1000) == "one thousand"

    def test_zero_and_negative(self):
        assert number_to_text(0) == "zero"
        assert number_to_text(-5) == "minus five"


class TestBase64Conversion:
    def test_round_trip_small_numbers(self):
        for n in [1, 5, 10, 255]:
            b64 = number_to_base64(n)
            back = base64_to_number(b64)
            assert back == n

    def test_invalid_base64(self):
        with pytest.raises(ValueError):
            base64_to_number("invalid$")

    def test_negative_number(self):
        with pytest.raises(ValueError):
            number_to_base64(-1)

    def test_zero_bug_exposing(self):
        """Bug-exposing: should be able to convert 0 to base64 and back"""
        b64 = number_to_base64(0)
        back = base64_to_number(b64)
        assert back == 0


# ----------------------------
# API (Flask) endpoint tests
# ----------------------------

class TestFlaskEndpoints:
    def test_index_route(self, client):
        r = client.get("/")
        assert r.status_code == 200

    # ---- Exhaustive input→output combinations ----
    @pytest.mark.parametrize("input_type,input_value,expected_decimal", [
        ("text", "five", 5),
        ("binary", "101", 5),
        ("octal", "5", 5),
        ("decimal", "5", 5),
        ("hexadecimal", "5", 5),
    ])
    @pytest.mark.parametrize("output_type,expected_value", [
        ("text", "five"),
        ("binary", "101"),
        ("octal", "5"),
        ("decimal", "5"),
        ("hexadecimal", "5"),
    ])
    def test_all_input_to_all_output(self, client, input_type, input_value,
                                     expected_decimal, output_type, expected_value):
        """Covers full conversion cross-product except base64 (separately tested)"""
        data = {"input": input_value, "inputType": input_type, "outputType": output_type}
        resp = client.post("/convert", data=json.dumps(data), content_type="application/json")
        result = json.loads(resp.data)
        assert result["error"] is None
        assert result["result"] == expected_value

    def test_decimal_to_base64_and_back(self, client):
        """Decimal -> Base64 -> Decimal"""
        data1 = {"input": "42", "inputType": "decimal", "outputType": "base64"}
        resp1 = client.post("/convert", data=json.dumps(data1), content_type="application/json")
        base64_val = json.loads(resp1.data)["result"]

        data2 = {"input": base64_val, "inputType": "base64", "outputType": "decimal"}
        resp2 = client.post("/convert", data=json.dumps(data2), content_type="application/json")
        result2 = json.loads(resp2.data)
        assert result2["result"] == "42"

    # ---- Error handling ----
    def test_invalid_input_type(self, client):
        data = {"input": "5", "inputType": "foobar", "outputType": "decimal"}
        resp = client.post("/convert", data=json.dumps(data), content_type="application/json")
        result = json.loads(resp.data)
        assert result["result"] is None
        assert "Invalid input type" in result["error"]

    def test_invalid_output_type(self, client):
        data = {"input": "5", "inputType": "decimal", "outputType": "foobar"}
        resp = client.post("/convert", data=json.dumps(data), content_type="application/json")
        result = json.loads(resp.data)
        assert result["result"] is None
        assert "Invalid output type" in result["error"]

    @pytest.mark.parametrize("input_type,input_value", [
        ("binary", "102"),
        ("octal", "89"),
        ("hexadecimal", "xyz"),
        ("text", "foobar"),
        ("base64", "not_base64$$"),
    ])
    def test_invalid_inputs(self, client, input_type, input_value):
        data = {"input": input_value, "inputType": input_type, "outputType": "decimal"}
        resp = client.post("/convert", data=json.dumps(data), content_type="application/json")
        result = json.loads(resp.data)
        assert result["result"] is None
        assert result["error"] is not None

    def test_zero_conversions(self, client):
        """Zero across all supported output types"""
        for output_type, expected in [
            ("text", "zero"),
            ("binary", "0"),
            ("octal", "0"),
            ("decimal", "0"),
            ("hexadecimal", "0"),
            ("base64", base64.b64encode((0).to_bytes(1, "little")).decode()),
        ]:
            data = {"input": "0", "inputType": "decimal", "outputType": output_type}
            resp = client.post("/convert", data=json.dumps(data), content_type="application/json")
            result = json.loads(resp.data)
            assert result["result"] == expected


# ----------------------------
# Bug detection focus
# ----------------------------

class TestBugDetection:
    def test_bug_base64_endianness_exposing(self):
        """Bug-exposing: should use little-endian encoding"""
        n = 258
        expected_le = base64.b64encode(n.to_bytes(2, "little")).decode()
        actual = number_to_base64(n)
        assert actual == expected_le  # Fails until implementation is fixed