#[derive(Default)]
pub struct QueuePlan {pub routes:Vec<Option<String>>,pub index:usize,pub running:bool,pub stopped:bool}
impl QueuePlan {
 pub fn new(routes:Vec<String>)->Self{Self{routes:if routes.is_empty(){vec![None]}else{routes.into_iter().map(Some).collect()},..Self::default()}}
 pub fn next(&mut self)->Option<Option<String>>{if self.running||self.stopped||self.index>=self.routes.len(){return None;}let route=self.routes[self.index].clone();self.index+=1;self.running=true;Some(route)}
 pub fn terminal(&mut self,success:bool){self.running=false;if !success{self.stopped=true;}}
 pub fn cancel(&mut self){self.stopped=true;}
}
#[cfg(test)]mod tests{use super::*;
 #[test]fn ordered_exclusive_and_repeat(){let mut q=QueuePlan::new(vec!["a".into(),"b".into(),"c".into()]);for r in ["a","b","c"]{assert_eq!(q.next(),Some(Some(r.into())));assert_eq!(q.next(),None);q.terminal(true);}assert_eq!(q.next(),None);let mut again=QueuePlan::new(vec!["a".into(),"b".into()]);assert_eq!(again.next(),Some(Some("a".into())));}
 #[test]fn failure_cancel_and_default(){for cancel in [false,true]{let mut q=QueuePlan::new(vec!["a".into(),"b".into()]);q.next();if cancel{q.cancel();q.terminal(true)}else{q.terminal(false)}assert_eq!(q.next(),None);}assert_eq!(QueuePlan::new(vec![]).next(),Some(None));}
}
