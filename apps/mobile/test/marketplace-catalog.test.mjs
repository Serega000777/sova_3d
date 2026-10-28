import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/(tabs)/market.tsx", import.meta.url), "utf8");
const detail = readFileSync(new URL("../app/market/[id].tsx", import.meta.url), "utf8");
const cart = readFileSync(new URL("../app/cart.tsx", import.meta.url), "utf8");
const creator = readFileSync(new URL("../app/creator/[handle].tsx", import.meta.url), "utf8");
const feed = readFileSync(new URL("../app/market-feed.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");
const floorPlans = readFileSync(new URL("../src/MarketplaceFloorPlans.tsx", import.meta.url), "utf8");
const facadeSchedule = readFileSync(new URL("../src/MarketplaceFacadeSchedule.tsx", import.meta.url), "utf8");
const facadeCompatibility = readFileSync(new URL("../src/MarketplaceFacadeCompatibility.tsx", import.meta.url), "utf8");
const sitePlan = readFileSync(new URL("../src/MarketplaceSitePlan.tsx", import.meta.url), "utf8");
const siteCompatibility = readFileSync(new URL("../src/MarketplaceSiteCompatibility.tsx", import.meta.url), "utf8");
const marketplaceFiles = readFileSync(new URL("../src/marketplace-files.ts", import.meta.url), "utf8");
const modelPreview = readFileSync(new URL("../src/marketplace-model-preview.ts", import.meta.url), "utf8");

test("alternate reference 51/02 shows only canonical saved listing thumbnails", () => {
  assert.match(source, /listing\.thumbnail_asset_id/);
  assert.match(source, /client\.download\(listing\.thumbnail_asset_id\)/);
  assert.match(source, /thumbnailUrls\[listing\.id\]/);
  assert.match(source, /<Image/);
  assert.doesNotMatch(source, /versionThumbnailUrl|ensureVersionThumbnail|createThumbnail/);
});

test("alternate reference 51/03 opens a read-only listing card before acquisition", () => {
  assert.match(source, /router\.push\(`\/market\/\$\{listing\.id\}`\)/);
  assert.doesNotMatch(source, /acquireListing/);
  assert.match(detail, /client\.getListing\(id\)/);
  assert.match(detail, /listing\.description/);
  assert.match(detail, /listing\.license_name/);
  assert.match(detail, /listing\.available_formats/);
  assert.match(detail, /listingThumbnails\(listing\)/);
});

test("M04 previews only the exact saved listing model in supported native formats", () => {
  assert.match(detail, /client\.download\(item\.model_asset_id\)/);
  assert.match(detail, /verifiedMarketplaceModelPreview\(item\.model_asset_id, download\)/);
  assert.match(detail, /<ModelViewer/);
  assert.match(detail, /viewerMode === "wire" \? "mesh" : "source"/);
  assert.match(detail, /onMeasure=\{setViewerSize\}/);
  assert.match(detail, /Осмотр/);
  assert.match(detail, /Каркас/);
  assert.match(detail, /Размеры/);
  assert.match(modelPreview, /download\.asset_id !== expectedAssetId/);
  assert.match(modelPreview, /format !== "stl" && format !== "glb"/);
  assert.doesNotMatch(detail, /convert|createThumbnail|ensureVersionThumbnail/);
});

test("bundle cards render canonical components and only saved component thumbnails", () => {
  assert.match(detail, /\(item\.components \?\? \[\]\)\.map/);
  assert.match(detail, /component\.thumbnail_asset_id/);
  assert.match(detail, /client\.download\(component\.thumbnail_asset_id\)/);
  assert.match(detail, /componentThumbnailUrls\[component\.id\]/);
  assert.match(detail, /Состав набора/);
  assert.match(detail, /component\.label/);
  assert.match(detail, /component\.print_verified\?\.status === "green"/);
  assert.match(detail, /Сохранённое превью компонента недоступно/);
  assert.doesNotMatch(detail, /ensureVersionThumbnail|createThumbnail/);
});

test("house listings render canonical metadata and interactive immutable floor plans", () => {
  assert.match(detail, /listing\.house\.gross_floor_area_m2/);
  assert.match(detail, /listing\.house\.length_mm/);
  assert.match(detail, /listing\.house\.rooms\.map/);
  assert.match(detail, /listing\.floor_plans\.length > 0/);
  assert.match(detail, /<MarketplaceFloorPlans levels=\{listing\.floor_plans\}/);
  assert.match(floorPlans, /type FloorPlanRow = Listing\["floor_plans"\]\[number\]/);
  assert.match(floorPlans, /<PlanViewer plan=\{plan\} selection=\{selection\} onSelect=\{setSelection\}/);
  assert.match(floorPlans, /setSelectedFloor\(level\.floor_index\)/);
  assert.match(floorPlans, /setSelection\(null\)/);
  assert.match(floorPlans, /selected\.elevation_mm/);
  assert.doesNotMatch(detail, /autoLayoutFloorPlan|createFloorPlan/);
});

test("house listing documents remain authenticated, immutable, and fail closed before native sharing", () => {
  assert.match(detail, /shareHouseDocument\(client, listing\.id\)/);
  assert.match(detail, /shareHouseSpreadsheet\(client, listing\.id\)/);
  assert.match(detail, /PDF и XLSX строятся сервером только из доказательств опубликованной неизменяемой версии/);
  assert.match(marketplaceFiles, /client\.downloadHouseDocument\(listingId\)/);
  assert.match(marketplaceFiles, /client\.downloadHouseSpreadsheet\(listingId\)/);
  assert.match(marketplaceFiles, /blob\.size > 0 && mime === expectedMime/);
  assert.match(marketplaceFiles, /new File\(Paths\.cache, value\.fileName\)/);
  assert.match(marketplaceFiles, /await shareAsync\(file\.uri/);
  assert.doesNotMatch(detail, /Linking\.openURL\([^)]*house/);
});

test("exact-facade listings render the canonical immutable schedule", () => {
  assert.match(detail, /listing\.facade \? <MarketplaceFacadeSchedule facade=\{listing\.facade\}/);
  assert.match(facadeSchedule, /type Facade = NonNullable<Listing\["facade"\]>/);
  assert.match(facadeSchedule, /facade\.wall_thickness_mm/);
  assert.match(facadeSchedule, /facade\.floor_height_mm/);
  assert.match(facadeSchedule, /ROOF_LABELS\[facade\.roof\]/);
  assert.match(facadeSchedule, /facade\.openings\.map/);
  assert.match(facadeSchedule, /opening\.opening_id/);
  assert.doesNotMatch(facadeSchedule, /editFacade|composeFacade/);
});

test("facade compatibility is server-bound to exact addressed openings", () => {
  assert.match(detail, /<MarketplaceFacadeCompatibility client=\{client\} workspaceId=\{session\.workspaceId\} listing=\{listing\}/);
  assert.match(facadeCompatibility, /client\.listProjects\(workspaceId\)/);
  assert.match(facadeCompatibility, /client\.facadeCompatibility\(listing\.id, project\.id\)/);
  assert.match(facadeCompatibility, /report\.version_id !== project\.head_version_id/);
  assert.match(facadeCompatibility, /opening\.opening_id/);
  assert.match(facadeCompatibility, /opening\.matches\.map/);
  assert.match(facadeCompatibility, /Крепёж, направление монтажа, зазор и mesh-коллизии/);
});

test("yard listings render only the canonical immutable site composition", () => {
  assert.match(detail, /listing\.site_plan \? <MarketplaceSitePlan site=\{listing\.site_plan\}/);
  assert.match(sitePlan, /type SitePlan = NonNullable<Listing\["site_plan"\]>/);
  assert.match(sitePlan, /site\.plot_length_mm/);
  assert.match(sitePlan, /site\.corner_elevations_mm/);
  assert.match(sitePlan, /site\.house_dimensions_mm/);
  assert.match(sitePlan, /site\.path_points_mm/);
  assert.match(sitePlan, /site\.fence_sides/);
  assert.match(sitePlan, /site\.object_roles\.map/);
  assert.doesNotMatch(sitePlan, /composeSitePlan|createSitePlan/);
});

test("yard compatibility stays server-bound and version-verified", () => {
  assert.match(detail, /<MarketplaceSiteCompatibility client=\{client\} workspaceId=\{session\.workspaceId\} listingId=\{listing\.id\}/);
  assert.match(siteCompatibility, /client\.listProjects\(workspaceId\)/);
  assert.match(siteCompatibility, /client\.sitePlanCompatibility\(listingId, project\.id\)/);
  assert.match(siteCompatibility, /report\.version_id !== project\.head_version_id/);
  assert.match(siteCompatibility, /expected = Math\.min\(\.\.\.direct\)/);
  assert.match(siteCompatibility, /report\.terrain_corner_delta_mm/);
  assert.match(siteCompatibility, /Это не проверка нормативных отступов, земляных работ или коллизий/);
  assert.doesNotMatch(siteCompatibility, /fitRecommendation|semanticRecommendation/);
});

test("free acquisition and paid workspace cart remain explicit exact-listing actions", () => {
  assert.match(detail, /listing\.price_cents === 0/);
  assert.match(detail, /client\.acquireListing\(listing\.id, session\.workspaceId\)/);
  assert.match(detail, /client\.addToCart\(listing\.id, session\.workspaceId\)/);
  assert.match(detail, /router\.push\("\/cart"\)/);
  assert.match(detail, /onPress=\{\(\) => void actOnListing\(\)\}/);
  assert.match(detail, /В корзину/);
  assert.match(detail, /client\.addFavorite\(listing\.id\)/);
  assert.match(detail, /client\.removeFavorite\(listing\.id\)/);
});

test("mobile cart is canonical, removable, currency-exact, and has no fake checkout", () => {
  assert.match(source, /router\.push\("\/cart"\)/);
  assert.match(cart, /client\.getCart\(session\.workspaceId\)/);
  assert.match(cart, /client\.removeFromCart\(itemId, session\.workspaceId\)/);
  assert.match(cart, /cart\.totals\.map/);
  assert.match(cart, /listingPrice\(total\.amount_cents, total\.currency\)/);
  assert.match(cart, /accessibilityState=\{\{ disabled: true \}\}/);
  assert.match(cart, /Платёжный провайдер ещё не выбран/);
  assert.doesNotMatch(cart, /checkout|createOrder|acquireListing/);
});

test("paid listing reads exact workspace cart state before adding again", () => {
  assert.match(detail, /client\.getCart\(session\.workspaceId\)/);
  assert.match(detail, /cart\?\.items\.some\(\(candidate\) => candidate\.id === item\.id\)/);
  assert.match(detail, /if \(inCart\) \{[\s\S]*router\.push\("\/cart"\)/);
  assert.match(detail, /setInCart\(true\)/);
  assert.match(detail, /inCart \? "Открыть корзину"/);
});

test("listing creators open their canonical server page and follow state", () => {
  assert.match(detail, /router\.push\(`\/creator\/\$\{encodeURIComponent\(listing\.creator_handle\)\}`\)/);
  assert.match(creator, /client\.creatorPage\(handle\)/);
  assert.match(creator, /client\.myCreatorProfile\(\)/);
  assert.match(creator, /page\.profile\.followers/);
  assert.match(creator, /page\.profile\.listings/);
  assert.match(creator, /page\.collections/);
  assert.match(creator, /client\.followCreator\(page\.profile\.handle\)/);
  assert.match(creator, /client\.unfollowCreator\(page\.profile\.handle\)/);
  assert.match(creator, /router\.push\(`\/market\/\$\{listing\.id\}`\)/);
});

test("followed creators have a dedicated canonical server feed", () => {
  assert.match(source, /router\.push\("\/market-feed"\)/);
  assert.match(feed, /client\.marketplaceFeed\(\)/);
  assert.match(feed, /useFocusEffect/);
  assert.match(feed, /const next = await client\.marketplaceFeed\(\);[\s\S]*setListings\(next\)/);
  assert.match(feed, /listing\.creator_handle/);
  assert.match(feed, /router\.push\(`\/market\/\$\{listing\.id\}`\)/);
  assert.doesNotMatch(feed, /searchListings|listings\.filter\(/);
});

test("following feed resolves only canonical saved thumbnails", () => {
  assert.match(feed, /listing\.thumbnail_asset_id/);
  assert.match(feed, /client\.download\(listing\.thumbnail_asset_id\)/);
  assert.match(feed, /thumbnailUrls\[listing\.id\]/);
  assert.match(feed, /<Image/);
  assert.match(feed, /ПРЕВЬЮ НЕДОСТУПНО/);
  assert.doesNotMatch(feed, /createThumbnail|ensureVersionThumbnail/);
});

test("alternate reference 52/02 uses complete server-owned marketplace facets", () => {
  assert.match(source, /client\.marketplaceFacets\(\)/);
  assert.match(source, /verifiedFacets\(value\)/);
  assert.match(source, /value\.domains\.length !== MARKETPLACE_DOMAINS\.length/);
  assert.match(source, /Number\.isInteger\(facet\.count\)/);
  assert.match(source, /domain: selectedDomain \?\? undefined/);
  assert.match(source, /subcategory: selectedSubcategory \?\? undefined/);
  assert.match(source, /new Set\(facet\.subcategories\.map/);
  assert.match(source, /subcategory\.label_ru/);
  assert.match(source, /subcategory\.count/);
  assert.match(source, /setSelectedDomain\(facet\.id\)/);
  assert.match(source, /setSelectedSubcategory\(null\)/);
  assert.match(source, /setSelectedSubcategory\(\(current\) => current === subcategory\.id \? null : subcategory\.id\)/);
  assert.match(source, /Категории временно недоступны/);
});

test("marketplace search queries the canonical catalogue instead of the first local page", () => {
  assert.match(source, /setTimeout\(\(\) => setSearchTerm\(query\.trim\(\)\), 300\)/);
  assert.match(source, /q: searchTerm \|\| undefined/);
  assert.match(source, /const requestId = \+\+listingRequestId\.current/);
  assert.match(source, /requestId === listingRequestId\.current/);
  assert.doesNotMatch(source, /listings\.filter/);
});

test("marketplace browsing loads canonical result pages without duplicate listing ids", () => {
  assert.match(source, /const PAGE_SIZE = 24/);
  assert.match(source, /limit: PAGE_SIZE,[\s\S]*offset: 0/);
  assert.match(source, /const offset = nextOffset/);
  assert.match(source, /limit: PAGE_SIZE,[\s\S]*offset,/);
  assert.match(source, /new Set\(current\.map\(\(listing\) => listing\.id\)\)/);
  assert.match(source, /next\.filter\(\(listing\) => !seen\.has\(listing\.id\)\)/);
  assert.match(source, /setHasMore\(next\.length === PAGE_SIZE\)/);
  assert.match(source, /setNextOffset\(offset \+ next\.length\)/);
  assert.match(source, /Показать ещё/);
});

test("marketplace sort and free-only controls stay server-bound across every page", () => {
  assert.match(source, /type MarketSort = "popular" \| "newest" \| "cheapest"/);
  assert.match(source, /free: freeOnly \|\| undefined/);
  assert.match(source, /sort,/);
  assert.match(source, /setSort\(item\)/);
  assert.match(source, /setFreeOnly\(\(value\) => !value\)/);
  assert.match(source, /Только бесплатные/);
  assert.doesNotMatch(source, /listings\.sort/);
});

test("marketplace capability filters stay server-bound across every result page", () => {
  assert.equal(source.match(/editable: editableOnly \|\| undefined/g)?.length, 2);
  assert.equal(source.match(/has_2d_plan: has2dPlanOnly \|\| undefined/g)?.length, 2);
  assert.equal(source.match(/print_ready: printReadyOnly \|\| undefined/g)?.length, 2);
  assert.match(source, /setEditableOnly\(\(value\) => !value\)/);
  assert.match(source, /setHas2dPlanOnly\(\(value\) => !value\)/);
  assert.match(source, /setPrintReadyOnly\(\(value\) => !value\)/);
  assert.match(source, /Редактируемые/);
  assert.match(source, /С 2D-планом/);
  assert.match(source, /Готовы к печати/);
  assert.doesNotMatch(source, /listings\.filter/);
});

test("marketplace bundle filter stays server-bound across every result page", () => {
  assert.equal(source.match(/bundle_only: bundleOnly \|\| undefined/g)?.length, 2);
  assert.match(source, /setBundleOnly\(\(value\) => !value\)/);
  assert.match(source, /Только наборы/);
  assert.doesNotMatch(source, /listing\.is_bundle/);
});

test("marketplace fit envelope is validated and stays server-bound across every result page", () => {
  assert.equal(source.match(/max_width_mm: fit\?\.width/g)?.length, 2);
  assert.equal(source.match(/max_depth_mm: fit\?\.depth/g)?.length, 2);
  assert.equal(source.match(/max_height_mm: fit\?\.height/g)?.length, 2);
  assert.equal(source.match(/rotate_to_fit: fit\?\.rotate \|\| undefined/g)?.length, 2);
  assert.match(source, /Number\.isFinite\(value\) && value > 0 && value <= 1_000_000/);
  assert.match(source, /setFit\(\{ width: widthMm, depth: depthMm, height: heightMm, rotate: fitDraft\.rotate \}\)/);
  assert.match(source, /setFit\(null\)/);
  assert.match(source, /Каталог проверит только модели с измеренной геометрией/);
  assert.match(source, /Разрешить поворот/);
  assert.doesNotMatch(source, /listing\.(size_mm|dimensions)/);
});

test("marketplace format options come from the canonical registry and stay server-bound", () => {
  assert.match(client, /listFormats\(\)[\s\S]*"GET", "\/api\/v1\/formats"/);
  assert.match(source, /client\.listFormats\(\)/);
  assert.match(source, /verifiedMarketplaceFormats\(value\.formats\)/);
  assert.match(source, /\["mesh", "brep", "scene", "toolpath"\]\.includes\(format\.representation\)/);
  assert.equal(source.match(/format: selectedFormat \?\? undefined/g)?.length, 2);
  assert.match(source, /format\.display_name/);
  assert.match(source, /setSelectedFormat\(format\.id\)/);
  assert.doesNotMatch(source, /const MARKETPLACE_FORMATS/);
});

test("a missing or unreadable listing thumbnail keeps an honest placeholder", () => {
  assert.match(source, /\.catch\(\(\) => null\)/);
  assert.match(source, /ПРЕВЬЮ НЕДОСТУПНО/);
  assert.match(source, /Изображение товара не передано маркетплейсом/);
});
