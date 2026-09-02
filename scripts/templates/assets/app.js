(function () {
  "use strict";

  var toast = document.getElementById("toast");
  var toastTimer = null;

  function flash(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.hidden = true;
    }, 2600);
  }

  // The site works from any host, so absolute links are derived at runtime
  // rather than baked in at build time.
  function absolute(path) {
    return new URL(path, window.location.href).href;
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(field);
      ok ? resolve() : reject(new Error("copy refused"));
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action]");
    if (!button) return;
    var path = button.closest(".calendar-actions").dataset.path;
    var url = absolute(path);

    if (button.dataset.action === "copy") {
      copy(url).then(
        function () {
          flash("Lien copié");
        },
        function () {
          window.prompt("Copiez ce lien d'abonnement :", url);
        }
      );
    } else if (button.dataset.action === "subscribe") {
      window.location.href = url.replace(/^https?:/, "webcal:");
    }
  });

  // Search ---------------------------------------------------------------

  var search = document.getElementById("search");
  var count = document.getElementById("search-count");
  var empty = document.getElementById("empty");
  var leagues = Array.prototype.slice.call(document.querySelectorAll(".league"));
  var teams = Array.prototype.slice.call(document.querySelectorAll(".team"));
  var totalTeams = teams.length;

  function normalize(value) {
    return value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  teams.forEach(function (team) {
    team.dataset.needle = normalize(team.dataset.search);
  });
  leagues.forEach(function (league) {
    league.dataset.needle = normalize(league.dataset.search);
  });

  function filter() {
    var query = normalize(search.value);

    if (!query) {
      teams.forEach(function (team) {
        team.hidden = false;
      });
      leagues.forEach(function (league) {
        league.hidden = false;
      });
      empty.hidden = true;
      count.textContent = "";
      return;
    }

    var shown = 0;
    leagues.forEach(function (league) {
      var leagueMatches = league.dataset.needle.indexOf(query) !== -1;
      var visible = 0;
      Array.prototype.forEach.call(
        league.querySelectorAll(".team"),
        function (team) {
          var match = leagueMatches || team.dataset.needle.indexOf(query) !== -1;
          team.hidden = !match;
          if (match) visible += 1;
        }
      );
      league.hidden = visible === 0;
      shown += visible;
    });

    empty.hidden = shown !== 0;
    count.textContent =
      shown + " calendrier" + (shown > 1 ? "s" : "") + " sur " + totalTeams;
  }

  search.addEventListener("input", filter);

  // A ?q= parameter makes a filtered view shareable.
  var initial = new URLSearchParams(window.location.search).get("q");
  if (initial) {
    search.value = initial;
    filter();
  }
})();
