(function () {
    'use strict';

    const config = window.VAN_TRACKER_DRIVER_LIVE;
    const list = document.getElementById('attendance-list');
    const summary = document.getElementById('attendance-summary');
    const description = document.getElementById('attendance-description');
    const errorBox = document.getElementById('attendance-error');
    let currentTripId = null;
    let updateBusy = false;

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Attendance request failed.');
        return payload;
    }

    function setError(message) {
        errorBox.textContent = message;
        errorBox.hidden = !message;
    }

    function render(data) {
        currentTripId = data.trip_id || null;
        list.innerHTML = '';
        if (data.status === 'idle') {
            summary.textContent = 'No afternoon trip';
            summary.className = 'status-badge';
            description.textContent = 'Attendance appears when an afternoon trip is scheduled.';
            list.innerHTML = '<p class="muted">No attendance list is required.</p>';
            return;
        }

        summary.textContent = Number(data.boarded_count) + '/' + Number(data.total_count)
            + ' boarded';
        summary.className = 'status-badge '
            + (Number(data.boarded_count) === Number(data.total_count)
                ? 'status-active' : 'status-paused');
        description.textContent = data.editable
            ? 'Mark each child after they enter the van. Unmarked children trigger parent and staff alerts when the van leaves school.'
            : 'The van has left school. Attendance is now locked.';

        data.students.forEach(function (student) {
            const row = document.createElement('div');
            row.className = 'attendance-row '
                + (student.status === 'boarded' ? 'attendance-boarded' : 'attendance-pending');

            const identity = document.createElement('div');
            identity.className = 'attendance-student';
            const name = document.createElement('strong');
            name.textContent = student.name;
            const home = document.createElement('small');
            home.textContent = 'Stop ' + student.stop_order + ' · ' + student.pickup_location;
            identity.append(name, home);

            const controls = document.createElement('div');
            controls.className = 'attendance-controls';
            const label = document.createElement('label');
            label.className = 'attendance-radio';
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'attendance-' + student.student_id;
            radio.checked = student.status === 'boarded';
            radio.disabled = !data.editable;
            radio.dataset.studentId = student.student_id;
            const text = document.createElement('span');
            text.textContent = 'Boarded';
            label.append(radio, text);
            controls.appendChild(label);

            if (data.editable && student.status === 'boarded') {
                const clear = document.createElement('button');
                clear.type = 'button';
                clear.className = 'link-button attendance-clear';
                clear.textContent = 'Clear';
                clear.dataset.studentId = student.student_id;
                controls.appendChild(clear);
            }
            row.append(identity, controls);
            list.appendChild(row);
        });
    }

    async function refresh() {
        if (updateBusy) return;
        updateBusy = true;
        try {
            render(await requestJson(config.attendanceUrl));
            setError('');
        } catch (error) {
            setError(error.message);
        } finally {
            updateBusy = false;
        }
    }

    async function mark(studentId, boarded) {
        if (!currentTripId) return;
        try {
            await requestJson(config.attendanceUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': config.csrfToken
                },
                body: JSON.stringify({
                    trip_id: currentTripId,
                    student_id: Number(studentId),
                    boarded: boarded
                })
            });
            await refresh();
        } catch (error) {
            setError(error.message);
            await refresh();
        }
    }

    list.addEventListener('change', function (event) {
        if (event.target.matches('input[type="radio"][data-student-id]')) {
            mark(event.target.dataset.studentId, true);
        }
    });
    list.addEventListener('click', function (event) {
        const button = event.target.closest('.attendance-clear');
        if (button) mark(button.dataset.studentId, false);
    });

    refresh();
    setInterval(refresh, 4000);
})();
