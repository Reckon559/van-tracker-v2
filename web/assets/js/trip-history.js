(function () {
    'use strict';

    const search = document.getElementById('trip-history-search');
    const status = document.getElementById('trip-history-status');
    const count = document.getElementById('trip-history-count');
    const empty = document.getElementById('trip-history-empty');
    const rows = Array.from(document.querySelectorAll('[data-trip-history-row]'));
    if (!search || !status || !count || !rows.length) return;

    function filterRows() {
        const query = search.value.trim().toLowerCase();
        const selectedStatus = status.value;
        let visible = 0;

        rows.forEach(function (row) {
            const matchesQuery = !query
                || String(row.dataset.search || '').includes(query);
            const matchesStatus = !selectedStatus
                || row.dataset.status === selectedStatus;
            const show = matchesQuery && matchesStatus;
            row.hidden = !show;
            if (show) visible += 1;
        });

        count.textContent = visible + (visible === 1 ? ' trip' : ' trips');
        if (empty) empty.hidden = visible !== 0;
    }

    search.addEventListener('input', filterRows);
    status.addEventListener('change', filterRows);
})();
