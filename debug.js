const { JSDOM } = require('jsdom');
const dom = new JSDOM(`<body><wc-chess-board></wc-chess-board><div class='clock-component clock-top clock-player-turn'></div><div class='clock-component clock-bottom'></div></body>`);
const document = dom.window.document;
const bottomClock = document.querySelector('[data-cy="clock-bottom"], .clock-bottom .clock-component, .clock-component.clock-bottom');
const topClock = document.querySelector('[data-cy="clock-top"], .clock-top .clock-component, .clock-component.clock-top');
console.log(bottomClock != null, topClock != null, topClock && topClock.classList.contains('clock-player-turn'));
