(function () {
    "use strict";

    function debounce(callback, delay) {
        var timer;
        return function () {
            var args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () {
                callback.apply(null, args);
            }, delay);
        };
    }

    function initStudentAutocomplete(select) {
        if (!select || select.dataset.studentAutocompleteReady === "true") return;

        var multiple = select.multiple;
        var minimumLength = Number(select.dataset.minimumInputLength || 2);
        var wrapper = document.createElement("div");
        var control = document.createElement("div");
        var input = document.createElement("input");
        var results = document.createElement("div");
        var requestController = null;

        wrapper.className = "student-autocomplete";
        control.className = "student-autocomplete__control";
        input.className = "student-autocomplete__input";
        input.type = "search";
        input.autocomplete = "off";
        input.placeholder = select.dataset.placeholder || "Type to search students";
        results.className = "student-autocomplete__results";

        select.hidden = true;
        select.dataset.studentAutocompleteReady = "true";
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);
        wrapper.appendChild(control);
        wrapper.appendChild(results);
        control.appendChild(input);

        function selectedValues() {
            return Array.from(select.options)
                .filter(function (option) { return option.selected && option.value; })
                .map(function (option) { return String(option.value); });
        }

        function renderSelection() {
            control.querySelectorAll(".student-autocomplete__chip").forEach(function (chip) {
                chip.remove();
            });
            Array.from(select.options).forEach(function (option) {
                if (!option.selected || !option.value) return;
                var chip = document.createElement("span");
                var label = document.createElement("span");
                var remove = document.createElement("button");
                chip.className = "student-autocomplete__chip";
                label.textContent = (option.textContent || "").trim();
                remove.type = "button";
                remove.className = "student-autocomplete__remove";
                remove.innerHTML = "&times;";
                remove.setAttribute("aria-label", "Remove " + label.textContent);
                remove.addEventListener("click", function () {
                    option.selected = false;
                    if (!multiple) option.remove();
                    renderSelection();
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                });
                chip.appendChild(label);
                chip.appendChild(remove);
                control.insertBefore(chip, input);
            });
        }

        function closeResults() {
            results.classList.remove("is-open");
        }

        function showMessage(message) {
            results.innerHTML = "";
            var item = document.createElement("div");
            item.className = "student-autocomplete__message";
            item.textContent = message;
            results.appendChild(item);
            results.classList.add("is-open");
        }

        function addStudent(student) {
            var value = String(student.id);
            var option = Array.from(select.options).find(function (item) {
                return String(item.value) === value;
            });
            if (!multiple) {
                Array.from(select.options).forEach(function (item) {
                    item.selected = false;
                });
            }
            if (!option) {
                option = new Option(student.text, value, true, true);
                select.add(option);
            } else {
                option.textContent = student.text;
                option.selected = true;
            }
            input.value = "";
            closeResults();
            renderSelection();
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function renderResults(items) {
            results.innerHTML = "";
            var selected = selectedValues();
            var available = items.filter(function (item) {
                return !selected.includes(String(item.id));
            });
            if (!available.length) {
                showMessage(items.length ? "All matching students are already selected." : "No matching students found.");
                return;
            }
            available.forEach(function (student) {
                var button = document.createElement("button");
                var title = document.createElement("strong");
                var meta = document.createElement("small");
                button.type = "button";
                button.className = "student-autocomplete__option";
                title.textContent = student.text;
                meta.textContent = student.meta || "";
                button.appendChild(title);
                button.appendChild(meta);
                button.addEventListener("click", function () {
                    addStudent(student);
                });
                results.appendChild(button);
            });
            results.classList.add("is-open");
        }

        function appendFilter(url, parameter, selector) {
            if (!selector) return;
            var field = document.querySelector(selector);
            if (field && field.value) url.searchParams.set(parameter, field.value);
        }

        var search = debounce(function () {
            var query = input.value.trim();
            if (query.length < minimumLength) {
                closeResults();
                return;
            }
            if (requestController) requestController.abort();
            requestController = new AbortController();
            var url = new URL(select.dataset.autocompleteUrl, window.location.origin);
            url.searchParams.set("q", query);
            if (select.dataset.academicYear) url.searchParams.set("academic_year", select.dataset.academicYear);
            if (select.dataset.batch) url.searchParams.set("batch", select.dataset.batch);
            if (select.dataset.course) url.searchParams.set("course", select.dataset.course);
            appendFilter(url, "batch", select.dataset.batchSelector);
            appendFilter(url, "course", select.dataset.courseSelector);
            appendFilter(url, "academic_year", select.dataset.academicYearSelector);
            showMessage("Searching...");
            fetch(url.toString(), {
                headers: { "Accept": "application/json" },
                signal: requestController.signal
            })
                .then(function (response) {
                    if (!response.ok) throw new Error("Student search failed.");
                    return response.json();
                })
                .then(function (payload) {
                    renderResults(payload.results || []);
                })
                .catch(function (error) {
                    if (error.name !== "AbortError") showMessage("Unable to load students.");
                });
        }, 250);

        input.addEventListener("input", search);
        input.addEventListener("focus", function () {
            if (input.value.trim().length < minimumLength) {
                showMessage("Type at least " + minimumLength + " characters.");
            }
        });
        document.addEventListener("click", function (event) {
            if (!wrapper.contains(event.target)) closeResults();
        });
        renderSelection();
    }

    window.initStudentAutocompletes = function (root) {
        (root || document).querySelectorAll("select[data-student-autocomplete='true']").forEach(initStudentAutocomplete);
    };

    document.addEventListener("DOMContentLoaded", function () {
        window.initStudentAutocompletes(document);
    });
})();
