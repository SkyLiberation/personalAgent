"""Serve Toolathlon map tools using SerpApi in the evaluation container."""

import asyncio
from itertools import product
import json
import logging
import os
import re
from typing import Annotated, Literal, TypeVar, TypedDict

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError


TravelMode = Literal["driving", "walking", "bicycling", "transit"]
TRAVEL_MODES: dict[TravelMode, int] = {
    "driving": 0,
    "walking": 2,
    "bicycling": 1,
    "transit": 3,
}
PROVIDER_MODES: dict[TravelMode, str] = {
    "driving": "Driving",
    "walking": "Walking",
    "bicycling": "Cycling",
    "transit": "Transit",
}
METRIC_VALUE = Annotated[int, Field(strict=True, ge=0)]
COORDINATES = re.compile(r"\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\s*")
PlaceAddress = Annotated[str, Field(min_length=1)]
MatrixAddresses = Annotated[list[PlaceAddress], Field(min_length=1, max_length=25)]
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
Response = TypeVar("Response", bound=BaseModel)


class Measure(TypedDict):
    value: int
    text: str


class RouteStep(TypedDict, total=False):
    instructions: str
    distance: Measure
    duration: Measure
    travel_mode: str
    stops: list[str]


class Route(TypedDict):
    summary: str
    distance: Measure
    duration: Measure
    steps: list[RouteStep]


class MatrixElement(TypedDict, total=False):
    status: Literal["OK", "ZERO_RESULTS"]
    distance: Measure
    duration: Measure


class MatrixRow(TypedDict):
    elements: list[MatrixElement]


class DistanceMatrix(TypedDict):
    origin_addresses: list[str]
    destination_addresses: list[str]
    results: list[MatrixRow]


class Location(TypedDict):
    lat: float
    lng: float


class OpeningHours(TypedDict):
    weekday_text: list[str]


class Place(TypedDict, total=False):
    name: str
    formatted_address: str
    place_id: str
    location: Location
    rating: float
    types: list[str]
    formatted_phone_number: str
    website: str
    opening_hours: OpeningHours


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class PlaceResult(BaseModel):
    title: PlaceAddress
    address: str | None = None
    place_id: str | None = None
    gps_coordinates: GeoPoint | None = None
    rating: float | None = None
    category: str | list[str] = Field(default_factory=list, alias="type")


class PlaceDetails(PlaceResult):
    phone: str | None = None
    website: str | None = None
    hours: list[dict[str, str]] | dict[str, str] = Field(default_factory=list)


class PlacesResponse(BaseModel):
    local_results: list[PlaceResult] = Field(default_factory=list)
    place_results: PlaceResult | None = None
    error: str | None = None


class PlaceDetailsResponse(BaseModel):
    place_results: PlaceDetails | None = None
    error: str | None = None


class TransitStop(BaseModel):
    name: PlaceAddress


class Trip(BaseModel):
    title: str | None = None
    travel_mode: str | None = None
    distance: METRIC_VALUE | None = None
    formatted_distance: str | None = None
    duration: METRIC_VALUE | None = None
    formatted_duration: str | None = None
    details: list["Trip"] = Field(default_factory=list)
    start_stop: TransitStop | None = None
    end_stop: TransitStop | None = None
    stops: list[TransitStop] = Field(default_factory=list)


class Direction(BaseModel):
    travel_mode: str
    via: str = ""
    distance: METRIC_VALUE
    formatted_distance: Annotated[str, Field(min_length=1)]
    duration: METRIC_VALUE
    formatted_duration: Annotated[str, Field(min_length=1)]
    trips: list[Trip] = Field(default_factory=list)


class DirectionsResponse(BaseModel):
    directions: list[Direction] | None = None
    error: str | None = None


class RouteUnavailable(RuntimeError):
    """The provider returned no route for the requested travel mode."""


async def serpapi_search(
    client: httpx.AsyncClient,
    api_key: str,
    params: dict[str, str],
    response_type: type[Response],
) -> Response:
    try:
        response = await client.get(
            "https://serpapi.com/search.json",
            params={**params, "hl": "en", "api_key": api_key},
        )
    except httpx.RequestError:
        raise RuntimeError("SerpApi could not be reached.") from None
    if not response.is_success:
        raise RuntimeError(f"SerpApi returned HTTP {response.status_code}.")
    try:
        return response_type.model_validate_json(response.content)
    except ValidationError:
        raise RuntimeError("SerpApi returned an invalid Maps response.") from None


def place_payload(place: PlaceResult) -> Place:
    result: Place = {
        "name": place.title,
        "types": [place.category]
        if isinstance(place.category, str)
        else place.category,
    }
    if place.address is not None:
        result["formatted_address"] = place.address
    if place.place_id is not None:
        result["place_id"] = place.place_id
    if place.gps_coordinates is not None:
        result["location"] = {
            "lat": place.gps_coordinates.latitude,
            "lng": place.gps_coordinates.longitude,
        }
    if place.rating is not None:
        result["rating"] = place.rating
    return result


def place_details_payload(place: PlaceDetails) -> Place:
    result = place_payload(place)
    if place.phone is not None:
        result["formatted_phone_number"] = place.phone
    if place.website is not None:
        result["website"] = place.website
    hours_rows = place.hours if isinstance(place.hours, list) else [place.hours]
    hours = {day.lower(): value for row in hours_rows for day, value in row.items()}
    if all(hours.get(day.lower()) for day in WEEKDAYS):
        result["opening_hours"] = {
            "weekday_text": [f"{day}: {hours[day.lower()]}" for day in WEEKDAYS]
        }
    return result


def endpoint(label: str, value: str) -> dict[str, str]:
    coordinates = COORDINATES.fullmatch(value)
    if coordinates:
        latitude, longitude = map(float, coordinates.groups())
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return {f"{label}_coords": ",".join(coordinates.groups())}
    return {f"{label}_addr": value}


def route_steps(trip: Trip, mode: str) -> list[RouteStep]:
    travel_mode = (trip.travel_mode or mode).upper()
    if travel_mode == "CYCLING":
        travel_mode = "BICYCLING"
    if trip.details and not (trip.start_stop and trip.end_stop):
        return [
            step for detail in trip.details for step in route_steps(detail, travel_mode)
        ]
    if not trip.title:
        return []
    step: RouteStep = {"instructions": trip.title, "travel_mode": travel_mode}
    if trip.distance is not None and trip.formatted_distance:
        step["distance"] = {"value": trip.distance, "text": trip.formatted_distance}
    if trip.duration is not None and trip.formatted_duration:
        step["duration"] = {"value": trip.duration, "text": trip.formatted_duration}
    if trip.start_stop and trip.end_stop:
        step["stops"] = [
            stop.name for stop in (trip.start_stop, *trip.stops, trip.end_stop)
        ]
    return [step]


async def fetch_directions(
    client: httpx.AsyncClient,
    api_key: str,
    origin: str,
    destination: str,
    mode: TravelMode,
) -> list[Route]:
    params = {
        "engine": "google_maps_directions",
        **endpoint("start", origin),
        **endpoint("end", destination),
        "travel_mode": str(TRAVEL_MODES[mode]),
        "distance_unit": "1",
    }
    result = await serpapi_search(client, api_key, params, DirectionsResponse)
    if result.error:
        if result.error == "Google hasn't returned any results for this query.":
            raise RouteUnavailable("SerpApi found no route for these endpoints.")
        raise RuntimeError("SerpApi rejected the directions request.")
    if result.directions is None:
        raise RuntimeError("SerpApi directions response is missing routes.")
    matching = [
        route
        for route in result.directions
        if route.travel_mode == PROVIDER_MODES[mode]
    ]
    if not matching:
        raise RouteUnavailable(
            f"SerpApi did not return a {mode} route for these endpoints."
        )
    return [
        {
            "summary": route.via,
            "distance": {"value": route.distance, "text": route.formatted_distance},
            "duration": {"value": route.duration, "text": route.formatted_duration},
            "steps": [step for trip in route.trips for step in route_steps(trip, mode)],
        }
        for route in matching
    ]


async def distance_element(
    client: httpx.AsyncClient,
    api_key: str,
    origin: str,
    destination: str,
    mode: TravelMode,
) -> MatrixElement:
    try:
        route = (await fetch_directions(client, api_key, origin, destination, mode))[0]
    except RouteUnavailable:
        return {"status": "ZERO_RESULTS"}
    return {
        "status": "OK",
        "distance": route["distance"],
        "duration": route["duration"],
    }


async def distance_matrix(
    api_key: str, origins: list[str], destinations: list[str], mode: TravelMode
) -> DistanceMatrix:
    pairs = list(product(origins, destinations))
    if len(pairs) > 100:
        raise ValueError(
            "A distance matrix supports up to 100 origin–destination pairs."
        )
    elements: list[MatrixElement] = []
    batch_size = 6
    async with (
        asyncio.timeout(110),
        httpx.AsyncClient(timeout=12, trust_env=False) as client,
    ):
        for offset in range(0, len(pairs), batch_size):
            outcomes = await asyncio.gather(
                *(
                    distance_element(client, api_key, origin, destination, mode)
                    for origin, destination in pairs[offset : offset + batch_size]
                ),
                return_exceptions=True,
            )
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    raise outcome
                elements.append(outcome)
    width = len(destinations)
    return {
        "origin_addresses": origins,
        "destination_addresses": destinations,
        "results": [
            {"elements": elements[i : i + width]}
            for i in range(0, len(elements), width)
        ],
    }


def main() -> None:
    api_key = os.environ.get("SERP_API", "").strip()
    if not api_key:
        raise SystemExit("SERP_API is required.")
    # The provider authenticates in the query string. Keep HTTP request URLs out of logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    server = FastMCP("toolathlon-serpapi-maps", host="0.0.0.0", log_level="WARNING")

    @server.tool()
    async def maps_directions(
        origin: Annotated[
            str,
            Field(min_length=1, description="Starting point address or coordinates"),
        ],
        destination: Annotated[
            str, Field(min_length=1, description="Ending point address or coordinates")
        ],
        mode: Annotated[TravelMode, Field(description="Travel mode")] = "driving",
    ) -> str:
        """Get directions between two points."""
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            routes = await fetch_directions(client, api_key, origin, destination, mode)
        return json.dumps({"routes": routes}, ensure_ascii=False)

    @server.tool()
    async def maps_search_places(
        query: PlaceAddress,
        location: GeoPoint | None = None,
        radius: Annotated[int, Field(gt=0, le=50_000)] | None = None,
    ) -> str:
        """Search for places. Location and radius bias the returned results."""
        params = {"engine": "google_maps", "type": "search", "q": query}
        if location is not None:
            params.update(lat=str(location.latitude), lon=str(location.longitude))
            if radius is None:
                params["z"] = "15"
            else:
                params["m"] = str(radius * 2)
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            response = await serpapi_search(client, api_key, params, PlacesResponse)
        if response.error:
            raise RuntimeError("SerpApi rejected the place search.")
        places = response.local_results
        if not places and response.place_results is not None:
            places = [response.place_results]
        return json.dumps(
            {"places": [place_payload(place) for place in places]}, ensure_ascii=False
        )

    @server.tool()
    async def maps_place_details(place_id: PlaceAddress) -> str:
        """Look up details, including available opening hours, for a Google Place ID."""
        params = {"engine": "google_maps", "place_id": place_id}
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            response = await serpapi_search(
                client, api_key, params, PlaceDetailsResponse
            )
        if response.error or response.place_results is None:
            raise RuntimeError("SerpApi did not return details for this place ID.")
        return json.dumps(
            place_details_payload(response.place_results), ensure_ascii=False
        )

    @server.tool()
    async def maps_distance_matrix(
        origins: MatrixAddresses,
        destinations: MatrixAddresses,
        mode: TravelMode = "driving",
    ) -> str:
        """Calculate travel distance and time for every origin and destination pair."""
        matrix = await distance_matrix(api_key, origins, destinations, mode)
        return json.dumps(matrix, ensure_ascii=False)

    server.run(transport="sse")


if __name__ == "__main__":
    main()
