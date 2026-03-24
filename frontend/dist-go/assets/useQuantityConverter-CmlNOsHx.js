const n={XAU_PER_LOT:100,LOT_PRECISION:2};function e(r){return r==null||isNaN(r)?0:Number((r/n.XAU_PER_LOT).toFixed(n.LOT_PRECISION))}function o(r,t){return t==="bybit"?e(r):r}export{o as c,e as x};
