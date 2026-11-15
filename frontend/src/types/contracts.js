/** @typedef {{id:number,code:string,version:number,name:string,numerator:string,denominator:string,numerator_mode:string,denominator_mode:string,locked:boolean}} Metric 分子/分母可含 @代码:v版本.numerator|denominator 引用记号 */
/** @typedef {{id:number,class_code:string,day:string,mode:string,enrolled:number,attended:number,completed:number,refunds:number}} Fact */
/** @typedef {{id:number,metric_id:number,state:string,result:object,approval:string,note:string}} Snapshot 成功结果的result含冻结依赖deps、展开式expanded_numerator/denominator与ref_tree；旧格式快照无此三字段，页面需判空 */
