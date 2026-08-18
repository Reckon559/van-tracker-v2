(function () {
    'use strict';

    document.querySelectorAll('[data-location-picker]').forEach(function (root) {
        const nameInput = document.getElementById(root.dataset.nameInput);
        const latInput = document.getElementById(root.dataset.latInput);
        const lngInput = document.getElementById(root.dataset.lngInput);
        const searchInput = root.querySelector('[data-role="search"]');
        const searchButton = root.querySelector('[data-role="search-button"]');
        const resultsBox = root.querySelector('[data-role="results"]');
        const mapElement = root.querySelector('[data-role="map"]');
        const initialLat = Number.parseFloat(latInput.value) || 27.708;
        const initialLng = Number.parseFloat(lngInput.value) || 85.315;

        const map = L.map(mapElement).setView([initialLat, initialLng], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        let marker = null;
        if (latInput.value && lngInput.value) {
            marker = L.marker([initialLat, initialLng], {draggable: true}).addTo(map);
            bindMarker(marker);
        }

        function setLocation(lat, lng, label) {
            const numericLat = Number.parseFloat(lat);
            const numericLng = Number.parseFloat(lng);
            latInput.value = numericLat.toFixed(8);
            lngInput.value = numericLng.toFixed(8);
            if (label) {
                nameInput.value = label;
                searchInput.value = label;
            }
            if (marker) map.removeLayer(marker);
            marker = L.marker([numericLat, numericLng], {draggable: true}).addTo(map);
            bindMarker(marker);
            map.setView([numericLat, numericLng], 16);
        }

        function bindMarker(target) {
            target.on('dragend', function () {
                const position = target.getLatLng();
                latInput.value = position.lat.toFixed(8);
                lngInput.value = position.lng.toFixed(8);
            });
        }

        async function search() {
            const query = searchInput.value.trim();
            if (query.length < 3) return;
            resultsBox.classList.add('open');
            resultsBox.textContent = 'Searching…';

            try {
                const url = 'https://nominatim.openstreetmap.org/search?format=json'
                    + '&limit=6&countrycodes=np&q='
                    + encodeURIComponent(query + ', Kathmandu, Nepal');
                const response = await fetch(url, {
                    headers: {'Accept-Language': 'en'}
                });
                if (!response.ok) throw new Error('Search failed');
                const results = await response.json();
                resultsBox.textContent = '';

                if (!results.length) {
                    resultsBox.textContent = 'No locations found. Click the map instead.';
                    return;
                }

                results.forEach(function (result) {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'location-result';
                    button.textContent = result.display_name;
                    button.addEventListener('click', function () {
                        const shortName = result.display_name.split(',')[0];
                        setLocation(result.lat, result.lon, shortName);
                        resultsBox.classList.remove('open');
                    });
                    resultsBox.appendChild(button);
                });
            } catch (_error) {
                resultsBox.textContent = 'Search failed. Click the map or enter coordinates.';
            }
        }

        searchButton.addEventListener('click', search);
        searchInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                search();
            }
        });
        map.on('click', function (event) {
            setLocation(
                event.latlng.lat,
                event.latlng.lng,
                nameInput.value || 'Selected point'
            );
        });
    });
})();
