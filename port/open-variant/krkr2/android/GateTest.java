package pixel2.platformtest;
public final class GateTest {
 public static void main(String[] x) {
  long mb=1024, m=1024*1024;
  long[][] v={{-1,-1,0},{500*mb,50*m,0},{125*mb, -1,1},{126*mb,-1,0},{500*mb,230*m,1},{210*mb,135*m,1},{210*mb+1,135*m,0},{210*mb,135*m-1,0},{-1,230*m,1}};
  for(long[] t:v)if(EnginePressure.shouldNotify(t[0],t[1])!=(t[2]==1))throw new IllegalStateException();
  System.out.println("9 pressure gating cases passed");
  String[] empty={null,"",":","::"," : \t::\n","\r\f\u000b"};
  String[] real={"x","libtest.so",":libtest.so:"," :/vendor/lib/x.so\t","::a:b","："};
  for(String v1:empty) if(EarlyMain.hasRealPreload(v1)) throw new IllegalStateException("empty preload");
  for(String v1:real) if(!EarlyMain.hasRealPreload(v1)) throw new IllegalStateException("real preload");
  System.out.println("12 preload-list cases passed, including the board's literal colon");
 }
}
