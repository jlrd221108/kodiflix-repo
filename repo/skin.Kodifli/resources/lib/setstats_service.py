#!/usr/bin/python
# coding: utf-8

"""Publish aggregate metadata for the movie set selected in the Flix view."""

import json
import time

import xbmc
import xbmcgui


SUPPORTED_SKIN = "skin.Kodifli"
SET_ID_CONTROL = 56001
SET_TYPE_CONTROL = 56002
PROPERTY_COUNT = "kodiflix.helper.set_count"
PROPERTY_YEARS = "kodiflix.helper.set_years"
PROPERTY_RUNTIME = "kodiflix.helper.set_runtime"
HOME_WINDOW = xbmcgui.Window(10000)
FLIX_ACTIVE_CONDITION = (
	"Window.IsActive(videos) + [Control.IsVisible(56) | Control.IsVisible(57)]"
)
ACTIVE_POLL_SECONDS = 0.10
IDLE_POLL_SECONDS = 0.75
LIBRARY_UPDATE_DEBOUNCE_SECONDS = 2.0


def set_kodi_bool_setting(setting, value, warning):
	request = {
		"jsonrpc": "2.0",
		"id": 1,
		"method": "Settings.SetSettingValue",
		"params": {
			"setting": setting,
			"value": value,
		},
	}
	response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
	if "error" in response:
		xbmc.log(
			"{}: {}".format(warning, response["error"]),
			xbmc.LOGWARNING,
		)


def apply_video_library_preferences():
	set_kodi_bool_setting(
		"videolibrary.showallitems",
		False,
		"Kodiflix could not disable Kodi video library all-items entries",
	)
	set_kodi_bool_setting(
		"filelists.showparentdiritems",
		False,
		"Kodiflix could not disable Kodi parent-folder entries",
	)


def clear_properties():
	HOME_WINDOW.clearProperty(PROPERTY_COUNT)
	HOME_WINDOW.clearProperty(PROPERTY_YEARS)
	HOME_WINDOW.clearProperty(PROPERTY_RUNTIME)


def formatted_stats(movies):
	count = len(movies)
	count_label = "{} {}".format(count, "Movie" if count == 1 else "Movies")

	years = sorted(
		int(movie.get("year", 0))
		for movie in movies
		if int(movie.get("year", 0) or 0) > 0
	)
	if not years:
		years_label = ""
	elif years[0] == years[-1]:
		years_label = str(years[0])
	else:
		years_label = "{}\u2013{}".format(years[0], years[-1])

	total_seconds = sum(int(movie.get("runtime", 0) or 0) for movie in movies)
	total_minutes = total_seconds // 60
	hours = total_minutes // 60
	minutes = total_minutes % 60
	if not hours:
		runtime_label = "{} MIN".format(minutes)
	elif hours == 1:
		runtime_label = "1 HR {} MIN".format(minutes)
	else:
		runtime_label = "{} HRS {} MIN".format(hours, minutes)
	return count_label, years_label, runtime_label


def movie_set_movies(set_id):
	request = {
		"jsonrpc": "2.0",
		"id": 1,
		"method": "VideoLibrary.GetMovieSetDetails",
		"params": {
			"setid": set_id,
			"properties": [],
			"movies": {
				"properties": ["year", "runtime"],
				"limits": {"start": 0, "end": 10000},
			},
		},
	}
	response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
	return response.get("result", {}).get("setdetails", {}).get("movies", [])


def all_movie_set_stats():
	request = {
		"jsonrpc": "2.0",
		"id": 1,
		"method": "VideoLibrary.GetMovies",
		"params": {
			"properties": ["setid", "year", "runtime"],
			"limits": {"start": 0, "end": 100000},
		},
	}
	response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
	movies_by_set = {}
	for movie in response.get("result", {}).get("movies", []):
		set_id = int(movie.get("setid", 0) or 0)
		if set_id > 0:
			movies_by_set.setdefault(set_id, []).append(movie)
	return {
		set_id: formatted_stats(movies)
		for set_id, movies in movies_by_set.items()
	}


class SetStatsService(xbmc.Monitor):
	def __init__(self):
		super().__init__()
		self.previous_set_id = None
		self.cache = {}
		self.cache_loaded = False
		self.cache_dirty = False
		self.cache_dirty_since = 0.0

	def onNotification(self, _sender, method, _data):
		if method in (
			"VideoLibrary.OnUpdate",
			"VideoLibrary.OnRemove",
			"VideoLibrary.OnScanFinished",
			"VideoLibrary.OnCleanFinished",
		):
			self.cache_dirty = True
			self.cache_dirty_since = time.monotonic()

	def refresh_dirty_cache(self):
		if not self.cache_dirty:
			return
		if (
			time.monotonic() - self.cache_dirty_since
			< LIBRARY_UPDATE_DEBOUNCE_SECONDS
		):
			return
		self.cache = {}
		self.cache_loaded = False
		self.cache_dirty = False
		self.previous_set_id = None

	def preload_cache(self):
		try:
			self.cache.update(all_movie_set_stats())
		except Exception as error:
			xbmc.log(
				"Kodiflix set statistics preload failed: {}".format(error),
				xbmc.LOGERROR,
			)
		self.cache_loaded = True

	def publish(self, set_id):
		if set_id not in self.cache:
			self.cache[set_id] = formatted_stats(movie_set_movies(set_id))
		count_label, years_label, runtime_label = self.cache[set_id]
		HOME_WINDOW.setProperty(PROPERTY_COUNT, count_label)
		HOME_WINDOW.setProperty(PROPERTY_YEARS, years_label)
		HOME_WINDOW.setProperty(PROPERTY_RUNTIME, runtime_label)

	def run(self):
		while not self.abortRequested():
			if xbmc.getSkinDir() != SUPPORTED_SKIN:
				clear_properties()
				self.previous_set_id = None
				self.cache_loaded = False
				self.waitForAbort(2)
				continue

			if not xbmc.getCondVisibility(FLIX_ACTIVE_CONDITION):
				if self.previous_set_id is not None:
					clear_properties()
				self.previous_set_id = None
				self.waitForAbort(IDLE_POLL_SECONDS)
				continue

			self.refresh_dirty_cache()
			if not self.cache_loaded:
				self.preload_cache()

			db_type = xbmc.getInfoLabel(
				"Control.GetLabel({})".format(SET_TYPE_CONTROL)
			).lower()
			set_id_label = xbmc.getInfoLabel(
				"Control.GetLabel({})".format(SET_ID_CONTROL)
			)
			try:
				set_id = int(set_id_label) if db_type == "set" else None
			except (TypeError, ValueError):
				set_id = None

			if set_id != self.previous_set_id:
				self.previous_set_id = set_id
				if set_id is None:
					clear_properties()
				else:
					try:
						self.publish(set_id)
					except Exception as error:
						clear_properties()
						xbmc.log(
							"Kodiflix set statistics failed: {}".format(error),
							xbmc.LOGERROR,
						)

			self.waitForAbort(ACTIVE_POLL_SECONDS)


if __name__ == "__main__":
	apply_video_library_preferences()
	SetStatsService().run()
