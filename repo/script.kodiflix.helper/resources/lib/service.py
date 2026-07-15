#!/usr/bin/python
# coding: utf-8

"""Kodiflix adaptive artwork service.

This GPL-2.0 implementation uses the same architectural method as Nimbus
Helper: a hidden skin image control exposes the current artwork path, Pillow
generates a cached saturated Gaussian-blur derivative, and a home-window
property returns that generated image to the skin.
"""

import hashlib
import math
import os
import time
import urllib.parse
import colorsys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from PIL import Image, ImageEnhance, ImageFilter, ImageStat


SUPPORTED_SKIN = "skin.Kodifli"
SOURCE_CONTROL_ID = 56000
OUTPUT_PROPERTY = "kodiflix.helper.flix_blurred"
COLOR_PROPERTY = "kodiflix.helper.flix_color"
COLOR_NOALPHA_PROPERTY = "kodiflix.helper.flix_color_noalpha"
TEXT_COLOR_PROPERTY = "kodiflix.helper.flix_textcolor"
CACHE_TOKEN_PROPERTY = "kodiflix.helper.cache_token"
DEFAULT_RADIUS = 30
DEFAULT_SATURATION = 1.5
TARGET_SIZE = (200, 200)
CACHE_MAX_BYTES = 128 * 1024 * 1024
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEBOUNCE_SECONDS = 0.18
ACTIVE_POLL_SECONDS = 0.10
LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

ADDON = xbmcaddon.Addon()
HOME_WINDOW = xbmcgui.Window(10000)
CACHE_DIRECTORY = xbmcvfs.translatePath(
	"special://profile/addon_data/{}/blur_cache/".format(ADDON.getAddonInfo("id"))
)

def ensure_cache_directory():
	if not xbmcvfs.exists(CACHE_DIRECTORY):
		xbmcvfs.mkdirs(CACHE_DIRECTORY)


def clear_properties():
	HOME_WINDOW.clearProperty(OUTPUT_PROPERTY)
	HOME_WINDOW.clearProperty(COLOR_PROPERTY)
	HOME_WINDOW.clearProperty(COLOR_NOALPHA_PROPERTY)
	HOME_WINDOW.clearProperty(TEXT_COLOR_PROPERTY)


def prune_cache():
	ensure_cache_directory()
	now = time.time()
	entries = []

	try:
		for entry in os.scandir(CACHE_DIRECTORY):
			if not entry.is_file() or not entry.name.lower().endswith(".png"):
				continue
			try:
				stats = entry.stat()
				if now - stats.st_mtime > CACHE_MAX_AGE_SECONDS:
					os.remove(entry.path)
					continue
				entries.append((entry.path, stats.st_size, stats.st_mtime))
			except OSError:
				continue
	except OSError:
		return

	total_size = sum(entry[1] for entry in entries)
	for path, size, _modified in sorted(entries, key=lambda entry: entry[2]):
		if total_size <= CACHE_MAX_BYTES:
			break
		try:
			os.remove(path)
			total_size -= size
		except OSError:
			continue


def setting_number(name, fallback, number_type):
	value = xbmc.getInfoLabel("Skin.String({})".format(name))
	try:
		return number_type(value) if value else fallback
	except (TypeError, ValueError):
		return fallback


def normalise_source(source):
	source = urllib.parse.unquote(source or "")
	if source.startswith("image://"):
		source = source[8:]
		if source.endswith("/"):
			source = source[:-1]
	return source


def cache_filename(source, radius, saturation):
	digest = hashlib.md5(source.encode("utf-8")).hexdigest()
	saturation_key = str(saturation).replace(".", "_")
	return os.path.join(
		CACHE_DIRECTORY,
		"{}_r{}_s{}.png".format(digest, radius, saturation_key),
	)


def cached_candidates(source):
	candidates = []
	for value in (source, "image://{}/".format(source)):
		thumb = xbmc.getCacheThumbName(value)
		stem = thumb[:-4]
		candidates.extend(
			(
				"special://profile/Thumbnails/{}/{}.jpg".format(thumb[0], stem),
				"special://profile/Thumbnails/{}/{}.png".format(thumb[0], stem),
				"special://profile/Thumbnails/Video/{}/{}".format(thumb[0], thumb),
			)
		)
	return candidates


def open_source(source, temporary_path):
	source = normalise_source(source)

	for candidate in cached_candidates(source):
		if xbmcvfs.exists(candidate):
			try:
				with Image.open(xbmcvfs.translatePath(candidate)) as image:
					return image.copy()
			except Exception:
				pass

	translated = xbmcvfs.translatePath(source)
	if translated and os.path.exists(translated):
		with Image.open(translated) as image:
			return image.copy()

	if xbmcvfs.exists(source) and xbmcvfs.copy(source, temporary_path):
		try:
			with Image.open(temporary_path) as image:
				return image.copy()
		finally:
			xbmcvfs.delete(temporary_path)

	return None


def create_blur(source, radius, saturation):
	ensure_cache_directory()
	target = cache_filename(source, radius, saturation)

	if xbmcvfs.exists(target):
		try:
			os.utime(target, None)
		except OSError:
			pass
		return target

	image = open_source(source, target + ".source")
	if image is None:
		return ""

	image.thumbnail(TARGET_SIZE, LANCZOS)
	image = image.convert("RGB")

	statistics = ImageStat.Stat(image)
	brightness = sum(statistics.mean[:3]) / (3.0 * 255.0)
	contrast = math.sqrt(
		0.241 * (statistics.stddev[0] ** 2)
		+ 0.691 * (statistics.stddev[1] ** 2)
		+ 0.068 * (statistics.stddev[2] ** 2)
	) / 100.0
	contrast = min(contrast, 1.0)

	if brightness > 0.7:
		image = ImageEnhance.Brightness(image).enhance(
			1.0 - (brightness - 0.7) * 0.5
		)

	image = ImageEnhance.Color(image).enhance(1.2 + 0.08 * (1.0 - contrast))

	for pass_number in range(3):
		image = image.filter(
			ImageFilter.GaussianBlur(radius * (pass_number + 1) / 3.0)
		)
		if contrast > 0.5:
			edge_preserve = image.filter(ImageFilter.EDGE_ENHANCE_MORE)
			image = Image.blend(image, edge_preserve, 0.15 * contrast)

	image = ImageEnhance.Contrast(image).enhance(1.04 + 0.04 * (1.0 - contrast))
	image = ImageEnhance.Color(image).enhance(
		saturation * (1.05 + 0.15 * (1.0 - contrast))
	)
	image.save(target, "PNG")
	return target


def image_colors(image_path):
	"""Return Nimbus-style dominant focus colour and readable text colour."""
	default_color = "FFCCCCCC"
	default_text_color = "FF141515"
	min_brightness = 0.65
	brightness_boost = 0.45

	def get_luminance(red, green, blue):
		red = red / 255 if red <= 10 else ((red / 255 + 0.055) / 1.055) ** 2.4
		green = green / 255 if green <= 10 else ((green / 255 + 0.055) / 1.055) ** 2.4
		blue = blue / 255 if blue <= 10 else ((blue / 255 + 0.055) / 1.055) ** 2.4
		return 0.2126 * red + 0.7152 * green + 0.0722 * blue

	def get_contrast_ratio(first_luminance, second_luminance):
		lighter = max(first_luminance, second_luminance)
		darker = min(first_luminance, second_luminance)
		return (lighter + 0.05) / (darker + 0.05)

	def get_best_text_color(background_color):
		background_luminance = get_luminance(
			background_color[0], background_color[1], background_color[2]
		)
		white_contrast = get_contrast_ratio(get_luminance(255, 255, 255), background_luminance)
		dark_contrast = get_contrast_ratio(get_luminance(20, 21, 21), background_luminance)
		if white_contrast >= dark_contrast * 0.42:
			return "FFFFFFFF"
		return "FF141515"

	try:
		with Image.open(image_path) as image:
			image = image.resize((50, 50))
			if image.mode != "RGB":
				image = image.convert("RGB")
			color_bins = {}

			for red, green, blue in image.getdata():
				simplified = (red // 10, green // 10, blue // 10)
				color_bins[simplified] = color_bins.get(simplified, 0) + 1

			dominant = max(color_bins, key=color_bins.get)
			red, green, blue = (component * 10 for component in dominant)
			hue, saturation, brightness = colorsys.rgb_to_hsv(
				red / 255.0, green / 255.0, blue / 255.0
			)

			if brightness < min_brightness:
				brightness = min(brightness + brightness_boost, 1.0)

			red, green, blue = (
				int(component * 255)
				for component in colorsys.hsv_to_rgb(hue, saturation, brightness)
			)
			color = "FF{:02x}{:02x}{:02x}".format(red, green, blue)
			text_color = get_best_text_color((red, green, blue))
			return color, text_color
	except Exception:
		return default_color, default_text_color


class KodiflixHelperService(xbmc.Monitor):
	def __init__(self):
		super().__init__()
		self.previous_key = ""
		self.pending_key = ""
		self.pending_since = 0.0

	@staticmethod
	def current_request():
		source = xbmc.getInfoLabel(
			"Control.GetLabel({})".format(SOURCE_CONTROL_ID)
		)
		radius = setting_number("Kodiflix.BlurRadius", DEFAULT_RADIUS, int)
		saturation = setting_number(
			"Kodiflix.BlurSaturation", DEFAULT_SATURATION, float
		)
		cache_token = HOME_WINDOW.getProperty(CACHE_TOKEN_PROPERTY)
		key = (
			"{}|{}|{}|{}".format(source, radius, saturation, cache_token)
			if source
			else ""
		)
		return source, radius, saturation, key

	def generate_and_publish(self, source, radius, saturation, request_key):
		try:
			blurred = create_blur(source, radius, saturation)
			if not blurred:
				return
			self.publish_blur(blurred, request_key)
		except Exception as error:
			xbmc.log(
				"Kodiflix Helper blur failed: {}".format(error), xbmc.LOGERROR
			)

	def publish_blur(self, blurred, request_key):
		color, text_color = image_colors(blurred)

		# Selection may have changed while Pillow was processing the image.
		if self.current_request()[3] != request_key:
			return

		HOME_WINDOW.setProperty(OUTPUT_PROPERTY, blurred)
		HOME_WINDOW.setProperty(COLOR_NOALPHA_PROPERTY, color[2:])
		HOME_WINDOW.setProperty(COLOR_PROPERTY, color)
		HOME_WINDOW.setProperty(TEXT_COLOR_PROPERTY, text_color)

	def run(self):
		prune_cache()
		while not self.abortRequested():
			if xbmc.getSkinDir() != SUPPORTED_SKIN:
				if self.previous_key:
					clear_properties()
				self.previous_key = ""
				self.pending_key = ""
				self.waitForAbort(5)
				continue

			source, radius, saturation, current_key = self.current_request()

			if current_key != self.previous_key:
				self.previous_key = current_key
				self.pending_key = current_key
				self.pending_since = time.monotonic()
				if not current_key:
					self.pending_key = ""
					self.waitForAbort(ACTIVE_POLL_SECONDS)
					continue
				cached_blur = cache_filename(source, radius, saturation)
				if xbmcvfs.exists(cached_blur):
					self.pending_key = ""
					self.publish_blur(cached_blur, current_key)

			if (
				self.pending_key
				and time.monotonic() - self.pending_since >= DEBOUNCE_SECONDS
			):
				request_key = self.pending_key
				self.pending_key = ""
				self.generate_and_publish(
					source, radius, saturation, request_key
				)

			self.waitForAbort(ACTIVE_POLL_SECONDS)


if __name__ == "__main__":
	KodiflixHelperService().run()
