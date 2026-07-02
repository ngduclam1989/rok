from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol, Tuple


Point = Tuple[float, float]


@dataclass(frozen=True)
class ImageProps:
    path: str
    screen_size: Tuple[int, int] = (1280, 720)
    box: Tuple[int, int, int, int] = (0, 0, 0, 0)
    threshold: float = 0.70
    least_diff: int = 25
    tab_name: str = "BOOSTS"


@dataclass(frozen=True)
class GatheringBoostAssets:
    active_buff_blue: ImageProps = ImageProps(
        "images/buffs/enhanced_gathering_blue.png"
    )
    active_buff_purple: ImageProps = ImageProps(
        "images/buffs/enhanced_gathering_purple.png"
    )
    item_blue: ImageProps = ImageProps(
        "images/items/enhanced_gathering_blue.png"
    )
    item_purple: ImageProps = ImageProps(
        "images/items/enhanced_gathering_purple.png"
    )


class BotAdapter(Protocol):
    """Implement these methods in the target project."""

    def back_to_map(self) -> None:
        ...

    def menu_should_open(self, should_open: bool) -> None:
        ...

    def tap(self, x: float, y: float, sleep_time: float = 0.1) -> None:
        ...

    def check_any(self, image_props: ImageProps) -> Tuple[bool, Optional[Point]]:
        ...


class GatheringBoostAction:
    items_icon_pos: Point = (930, 675)
    use_button_pos: Point = (980, 600)
    tab_positions = {
        "RESOURCES": (250, 80),
        "SPEEDUPS": (435, 80),
        "BOOSTS": (610, 80),
        "EQUIPMENT": (790, 80),
        "OTHER": (970, 80),
    }

    def __init__(
        self,
        bot: BotAdapter,
        assets: GatheringBoostAssets = GatheringBoostAssets(),
        logger: Callable[[str], None] = print,
    ) -> None:
        self.bot = bot
        self.assets = assets
        self.logger = logger

    def ensure_gathering_boost(self) -> bool:
        """Return True when an item was used, False when already active or missing."""
        self.bot.back_to_map()

        has_blue = self.has_buff(self.assets.active_buff_blue)
        has_purple = self.has_buff(self.assets.active_buff_purple)
        if has_blue or has_purple:
            self.logger("Gathering boost buff is already active.")
            return False

        self.logger("Gathering boost is not active. Trying to use boost item.")
        return self.use_first_available_item(
            [self.assets.item_blue, self.assets.item_purple]
        )

    def has_buff(self, buff_image: ImageProps) -> bool:
        found, _ = self.bot.check_any(buff_image)
        return found

    def use_first_available_item(self, item_images: Iterable[ImageProps]) -> bool:
        for item_image in item_images:
            if self.use_item(item_image):
                return True
        self.logger("No enhanced gathering item found in Boosts tab.")
        return False

    def use_item(self, item_image: ImageProps) -> bool:
        self.bot.menu_should_open(True)

        self.bot.tap(*self.items_icon_pos, sleep_time=2)
        self.bot.tap(*self.tab_positions[item_image.tab_name], sleep_time=1)

        found, item_pos = self.bot.check_any(item_image)
        if not found or item_pos is None:
            self.logger(f"Item image not found: {item_image.path}")
            return False

        self.bot.tap(*item_pos, sleep_time=0.5)
        self.bot.tap(*self.use_button_pos)
        self.logger(f"Used item: {item_image.path}")
        return True
