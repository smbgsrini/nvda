# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2022-2023 NV Access Limited
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

# Needed for type hinting CaseInsensitiveDict
# Can be removed in a future version of python (3.8+)
from __future__ import annotations

import dataclasses
from datetime import datetime
import json
from typing import (
	TYPE_CHECKING,
	Any,
	Dict,
	Generator,
	List,
	Optional,
	Union,
)
from typing_extensions import (
	Protocol,
)

from requests.structures import CaseInsensitiveDict

import addonAPIVersion

from .channel import Channel
from .status import SupportsAddonState
from .version import (
	MajorMinorPatch,
	SupportsVersionCheck,
)

if TYPE_CHECKING:
	from addonHandler import (  # noqa: F401
		Addon as AddonHandlerModel,
		AddonBase as AddonHandlerBaseModel,
	)
	AddonGUICollectionT = Dict[Channel, CaseInsensitiveDict["_AddonGUIModel"]]
	"""
	Add-ons that have the same ID except differ in casing cause a path collision,
	as add-on IDs are installed to a case insensitive path.
	Therefore addon IDs should be treated as case insensitive.
	"""


AddonHandlerModelGeneratorT = Generator["AddonHandlerModel", None, None]


class _AddonGUIModel(SupportsAddonState, SupportsVersionCheck, Protocol):
	"""Needed to display information in add-on store.
	May come from manifest or add-on store data.
	"""
	addonId: str
	displayName: str
	description: str
	publisher: str
	addonVersionName: str
	channel: Channel
	homepage: Optional[str]
	minNVDAVersion: MajorMinorPatch
	lastTestedVersion: MajorMinorPatch
	legacy: bool
	"""
	Legacy add-ons contain invalid metadata
	and should not be accessible through the add-on store.
	"""

	@property
	def minimumNVDAVersion(self) -> addonAPIVersion.AddonApiVersionT:
		"""In order to support SupportsVersionCheck"""
		return self.minNVDAVersion

	@property
	def lastTestedNVDAVersion(self) -> addonAPIVersion.AddonApiVersionT:
		"""In order to support SupportsVersionCheck"""
		return self.lastTestedVersion

	@property
	def _addonHandlerModel(self) -> Optional["AddonHandlerModel"]:
		"""Returns the Addon model tracked in addonHandler, if it exists."""
		from ..dataManager import addonDataManager
		if addonDataManager is None:
			return None
		return addonDataManager._installedAddonsCache.installedAddons.get(self.addonId)

	@property
	def name(self) -> str:
		"""In order to support SupportsVersionCheck"""
		return self.addonId

	@property
	def listItemVMId(self) -> str:
		return f"{self.addonId}-{self.channel}"

	def asdict(self) -> Dict[str, Any]:
		jsonData = dataclasses.asdict(self)
		for field in jsonData:
			# dataclasses.asdict parses NamedTuples to JSON arrays,
			# rather than JSON object dictionaries,
			# which is expected by add-on infrastructure.
			fieldValue = getattr(self, field)
			if isinstance(fieldValue, MajorMinorPatch):
				jsonData[field] = fieldValue._asdict()
		return jsonData


@dataclasses.dataclass(frozen=True)
class AddonGUIModel(_AddonGUIModel):
	"""Can be displayed in the add-on store GUI.
	May come from manifest or add-on store data.
	"""
	addonId: str
	displayName: str
	description: str
	publisher: str
	addonVersionName: str
	channel: Channel
	homepage: Optional[str]
	minNVDAVersion: MajorMinorPatch
	lastTestedVersion: MajorMinorPatch
	legacy: bool = False
	"""
	Legacy add-ons contain invalid metadata
	and should not be accessible through the add-on store.
	"""


@dataclasses.dataclass(frozen=True)  # once created, it should not be modified.
class AddonStoreModel(_AddonGUIModel):
	"""
	Data from an add-on from the add-on store.
	"""
	addonId: str
	displayName: str
	description: str
	publisher: str
	addonVersionName: str
	channel: Channel
	homepage: Optional[str]
	license: str
	licenseURL: Optional[str]
	sourceURL: str
	URL: str
	sha256: str
	addonVersionNumber: MajorMinorPatch
	minNVDAVersion: MajorMinorPatch
	lastTestedVersion: MajorMinorPatch
	legacy: bool = False
	"""
	Legacy add-ons contain invalid metadata
	and should not be accessible through the add-on store.
	"""


@dataclasses.dataclass
class CachedAddonsModel:
	cachedAddonData: "AddonGUICollectionT"
	cachedAt: datetime
	# AddonApiVersionT or the string .network._LATEST_API_VER
	nvdaAPIVersion: Union[addonAPIVersion.AddonApiVersionT, str]


def _createStoreModelFromData(addon: Dict[str, Any]) -> AddonStoreModel:
	return AddonStoreModel(
		addonId=addon["addonId"],
		displayName=addon["displayName"],
		description=addon["description"],
		publisher=addon["publisher"],
		channel=Channel(addon["channel"]),
		addonVersionName=addon["addonVersionName"],
		addonVersionNumber=MajorMinorPatch(**addon["addonVersionNumber"]),
		homepage=addon.get("homepage"),
		license=addon["license"],
		licenseURL=addon.get("licenseURL"),
		sourceURL=addon["sourceURL"],
		URL=addon["URL"],
		sha256=addon["sha256"],
		minNVDAVersion=MajorMinorPatch(**addon["minNVDAVersion"]),
		lastTestedVersion=MajorMinorPatch(**addon["lastTestedVersion"]),
		legacy=addon.get("legacy", False),
	)


def _createGUIModelFromManifest(addon: "AddonHandlerBaseModel") -> AddonGUIModel:
	homepage = addon.manifest.get("url")
	if homepage == "None":
		# Manifest strings can be set to "None"
		homepage = None
	return AddonGUIModel(
		addonId=addon.name,
		displayName=addon.manifest["summary"],
		description=addon.manifest["description"],
		publisher=addon.manifest["author"],
		channel=Channel.EXTERNAL,
		addonVersionName=addon.version,
		homepage=homepage,
		minNVDAVersion=MajorMinorPatch(*addon.minimumNVDAVersion),
		lastTestedVersion=MajorMinorPatch(*addon.lastTestedNVDAVersion),
	)


def _createAddonGUICollection() -> "AddonGUICollectionT":
	"""
	Add-ons that have the same ID except differ in casing cause a path collision,
	as add-on IDs are installed to a case insensitive path.
	Therefore addon IDs should be treated as case insensitive.
	"""
	return {
		channel: CaseInsensitiveDict()
		for channel in Channel
		if channel != Channel.ALL
	}


def _createStoreCollectionFromJson(jsonData: str) -> "AddonGUICollectionT":
	"""Use json string to construct a listing of available addons.
	See https://github.com/nvaccess/addon-datastore#api-data-generation-details
	for details of the data.
	"""
	data: List[Dict[str, Any]] = json.loads(jsonData)
	addonCollection = _createAddonGUICollection()

	for addon in data:
		addonCollection[addon["channel"]][addon["addonId"]] = _createStoreModelFromData(addon)
	return addonCollection
