import {esc} from '../../utils/html.js';
const LABELS={draft:'草案',approved:'已签核',queued:'排队中',running:'计算中',done:'已完成',failed:'失败',preview:'预览中',scheduled:'已排期'};
export const badge=s=>`<span class=tag>${esc(LABELS[s]||s)}</span>`;
