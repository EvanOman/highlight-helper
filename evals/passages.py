"""Original neutral prose passages for the synthetic eval dataset.

These are written from scratch as plain, essay-like passages on neutral topics
(sailing, gardening, astronomy, printing, beekeeping, cartography, tides, bread).
They are NOT excerpts from any published work — the dataset must not embed
verbatim literary text. Each passage lists its paragraphs; the generator joins
them with blank lines to form the page's ``full_text``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    key: str
    title: str  # running header
    paragraphs: list[str]


PASSAGES: dict[str, Passage] = {
    "sailing": Passage(
        key="sailing",
        title="A Short Account of Small Boats",
        paragraphs=[
            "A sailboat does not move by being pushed so much as by being coaxed. "
            "The wind slides across the curve of the sail and, almost reluctantly, "
            "lends the hull a portion of its speed. A good sailor learns to read "
            "the water for the darker ruffled patches that mark a coming gust, and "
            "to ease the sheet a moment before the boat would otherwise heel too far.",
            "Trimming is the quiet craft at the center of it all. Too tight, and the "
            "sail stalls like a stubborn door; too loose, and it flutters uselessly "
            "along its leading edge. Between those two failures lies a narrow band of "
            "tension where the cloth holds its shape and the boat simply goes.",
        ],
    ),
    "gardening": Passage(
        key="gardening",
        title="Notes from a Working Garden",
        paragraphs=[
            "Every garden keeps its own calendar, and the wise grower learns to "
            "listen to it rather than to the printed one on the seed packet. Soil "
            "that stays cold long into spring will rot an early seed, while the same "
            "bed a fortnight later may coax it into a sturdy, unhurried start.",
            "Compost is the garden's memory. Each spent leaf and trimming returns to "
            "the heap, breaks down through a slow warmth, and comes back the "
            "following year as dark crumbling earth. Nothing in a good garden is "
            "truly thrown away; it is only lent to the pile for a season.",
            "Patience is the only tool that never wears out. A seedling cannot be "
            "hurried, and a fruit tree will fruit on its own schedule regardless of "
            "how often it is inspected. The grower who checks less and tends more "
            "usually gathers the fuller basket in the end.",
        ],
    ),
    "astronomy": Passage(
        key="astronomy",
        title="Looking Up: An Amateur's Guide",
        paragraphs=[
            "The night sky is not a fixed ceiling but a slow machine. Stars wheel "
            "overhead through the hours, and the whole pattern shifts a little "
            "westward each evening, so that the constellations of winter give way in "
            "time to the different company of summer.",
            "A small telescope changes everything and nothing. It cannot bring a "
            "galaxy close, yet it can resolve the rings of a distant planet into a "
            "clean bright ellipse, or split a single point of light into the pair of "
            "stars it always secretly was. The reward is not size but revelation.",
            "Dark skies are the true instrument. No lens can undo the glow of a city, "
            "and the observer who drives an hour into the countryside will see more "
            "with plain eyes than another sees through expensive glass beneath a "
            "streetlamp. The first rule of the hobby is simply to find the dark.",
        ],
    ),
    "printing": Passage(
        key="printing",
        title="The Long Road of the Printed Page",
        paragraphs=[
            "For most of human history a book was a scarce and costly thing, copied "
            "by hand one letter at a time. A single volume might occupy a scribe for "
            "the better part of a year, and the smallest slip of the pen was carried "
            "forward into every copy that followed. Knowledge moved slowly because "
            "its vessel was so laborious to make.",
            "The arrival of movable type did not so much invent printing as make it "
            "patient and repeatable. Individual letters, cast in metal and arranged "
            "into lines, could be inked, pressed onto a sheet, and then broken apart "
            "and set again for the next page. The labor that had once produced one "
            "book could now produce hundreds, each identical to the last.",
            "What followed was less a single invention than a long cascade of "
            "consequences. Cheaper books meant more readers; more readers meant a "
            "wider appetite for books, which pressed printers to work faster and to "
            "standardize their letters, their spelling, and eventually their whole "
            "trade. A quiet mechanical improvement in a workshop slowly rearranged "
            "who was allowed to know things.",
            "It is tempting to imagine the change as sudden, but it was not. For "
            "generations the printed book imitated the handwritten one, borrowing its "
            "cramped abbreviations and its ornamented capitals, as though embarrassed "
            "to admit it was a machine's work. Only gradually did the printed page "
            "learn to look like itself, plain and legible and unashamed.",
        ],
    ),
    "beekeeping": Passage(
        key="beekeeping",
        title="Keeping Bees Through the Year",
        paragraphs=[
            "A colony of bees is best understood not as many insects but as a single "
            "slow creature spread across a box. It breathes as one, warms itself as "
            "one, and in the depth of winter it draws inward into a shivering cluster "
            "that keeps its center warm while the world outside turns hard.",
            "The keeper's real work is done with the hands still. Most of what a "
            "beginner does to a hive is a disturbance, and the colony pays for every "
            "needless opening with lost heat and lost temper. To watch the entrance "
            "for a quarter hour teaches more than to pry the lid off twice a week.",
        ],
    ),
    "cartography": Passage(
        key="cartography",
        title="Measuring the Ground Beneath Us",
        paragraphs=[
            "Before a coastline could be drawn it had to be measured, and measuring "
            "the curved and stubborn surface of the world was the great unglamorous "
            "labor of cartography. Surveyors dragged their chains across fields and "
            "marshland, sighting from one hilltop to the next, building a scaffolding "
            "of triangulation that quietly underpinned every handsome published map.",
            "The trick that made it possible was disarmingly simple. If you know the "
            "length of one baseline and the angles to a distant landmark from each of "
            "its ends, the geometry of the triangle hands you the two remaining "
            "distances without your ever walking them. From a single carefully "
            "measured line an entire country could be chained together, hilltop by "
            "hilltop, into a consistent and trustworthy framework.",
            "What the finished map concealed was all this effort. A traveller "
            "unrolling a chart saw only clean coastlines and confident meridians, "
            "never the years of cold mornings and careful arithmetic that stood "
            "behind every reassuring line.",
        ],
    ),
    "tides": Passage(
        key="tides",
        title="The Breathing of the Sea",
        paragraphs=[
            "The tide is the ocean leaning, ever so slightly, toward the moon. Twice "
            "a day the water gathers itself and climbs the beach, and twice a day it "
            "withdraws, uncovering a strip of the world that belongs fully to neither "
            "land nor sea but is lent by turns to each.",
            "Sailors learn the tide before they learn much else, because it forgives "
            "nothing. A harbor that welcomes a boat at noon may strand it on bare mud "
            "by evening, and a current that helps the patient traveller will punish "
            "the one who fights it head on.",
        ],
    ),
    "bread": Passage(
        key="bread",
        title="On the Making of Ordinary Bread",
        paragraphs=[
            "Bread asks for very little and rewards attention out of all proportion "
            "to its ingredients. Flour, water, salt, and time will make a loaf; the "
            "difference between a poor one and a fine one lies almost entirely in how "
            "the time is spent rather than in what is added.",
            "Kneading is a conversation with the dough. At first it tears and resists "
            "and clings to the hands, but under steady working it grows smooth and "
            "elastic and begins to hold air. There comes a moment when the dough "
            "stops fighting and turns supple, and the baker who has felt that moment "
            "once will always recognize it again.",
            "The oven finishes what the hands began. In its heat the trapped air "
            "expands, the crust sets and browns, and the soft interior sets into a "
            "structure light enough to eat. What went in as a slack pale lump comes "
            "out transformed, and the whole kitchen is told about it by the smell.",
        ],
    ),
}
